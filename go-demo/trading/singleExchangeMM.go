package trading

import (
	"context"
	"fmt"
	"sync"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	accountsPB "github.com/InjectiveLabs/sdk-go/exchange/accounts_rpc/pb"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
	"github.com/tendermint/tendermint/libs/rand"
)

type SingleExchangeMM struct {
	Exchanges []string
	Symbol    []string
	Bids      [][]interface{}
	Asks      [][]interface{}
}

func (s *tradingSvc) SingleExchangeMM(ctx context.Context, m *spotExchangePB.SpotMarketInfo, idx int, interval time.Duration) {
	s.logger.Infof("✅ Start strategy for %s spot market.", m.Ticker)
	ErrCh := make(chan map[string]interface{}, 10) // isolated err channel for each strategy
	var Initial bool = true
	//var rollBack bool = false
	//var rollBackCountDown time.Time
	var wg sync.WaitGroup
	var printOrdersTime time.Time
	var single SingleExchangeMM

	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	marketInfo := SpotMarketToMarketInfo(m)
	marketInfo.StopStrategy = false
	marketInfo.StopStrategyForDay = false
	marketInfo.MaxPositionPct = decimal.NewFromInt(int64(s.maxPositionPct)).Div(decimal.NewFromInt(100))
	marketInfo.MinPnlPct = decimal.NewFromInt(int64(s.minPnlPct)).Div(decimal.NewFromInt(100))
	marketInfo.MaxDDPct = decimal.NewFromInt(int64(s.maxDDPct)).Div(decimal.NewFromInt(100))
	marketInfo.HistoricalPrices = make([]decimal.Decimal, 0, s.historySec)
	marketInfo.HistoricalValues = make([]decimal.Decimal, 0, s.historySec)
	// set max order value from .env
	marketInfo.MaxOrderValue = decimal.NewFromInt(int64(s.maxOrderValue))
	// set as model parameters
	marketInfo.RiskAversion = 0.1
	marketInfo.FillIndensity = 0.5

	marketInfo.LastSendMessageTime = make([]time.Time, 4) // depends on how many critical alerts wanna send with 10 min interval
	single.Exchanges = []string{"Binance"}
	err := single.InitMMStrategy(idx, marketInfo, s)
	if err != nil {
		s.logger.Errorln("❌ Fail on initial client for cross exchange MM strategy.")
		return
	}

	// oracle price session, feat Binance
	for i, exch := range single.Exchanges {
		if exch == "Binance" {
			go s.BinanceTickerSession(ctx, &single, "spot", i, &ErrCh)
		}
	}
	time.Sleep(time.Second * 5)
	// inj stream trades session
	go s.StreamInjectiveSpotTradeSession(ctx, m, &subaccountID, marketInfo, &ErrCh)
	// inj stream orders session
	go s.StreamInjectiveSpotOrderSession(ctx, m, &subaccountID, marketInfo, &ErrCh)
	// test order session, if the testing order is active
	go s.SendTestOrder(ctx, marketInfo)
	// inital orders snapshot first
	s.InitialOrderList(ctx, m, &subaccountID, marketInfo, &ErrCh)

	for {
		select {
		case <-ctx.Done():
			s.appDown = true
			return
		case e := <-ErrCh: // wait for response first
			s.SessionErrHandling(&e)
			continue
		default:
			// renew critical errs list
			go s.RenewCriticalErrs()

			// get oracle price part
			err := marketInfo.GetOraclePrice(&single, s.historySec)
			if err != nil {
				s.logger.Infoln("Wait 5 sec for connecting reference price")
				time.Sleep(time.Second * 5)
				continue
			}

			// get account balance part
			var getAccountErr bool = false
			respBalance, err := s.accountsClient.SubaccountBalancesList(ctx, &accountsPB.SubaccountBalancesListRequest{
				SubaccountId: subaccountID.Hex(),
			})
			if err != nil || respBalance == nil {
				messageIdx := 0
				message := fmt.Sprintf("❌ Failed to get Injective subaccount balances for %s\n", marketInfo.Ticker)
				e := make(map[string]interface{})
				e["critical"] = true
				e["count"] = true
				e["wait"] = 20
				e["message"] = message
				ErrCh <- e
				if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
					go s.SendCritialAlertToDiscord(message)
					marketInfo.LastSendMessageTime[messageIdx] = time.Now()
				}
				getAccountErr = true
				continue
			}
			for _, balance := range respBalance.Balances {
				switch balance.Denom {
				case marketInfo.BaseDenom:
					avaiB, _ := decimal.NewFromString(balance.Deposit.AvailableBalance)
					marketInfo.BaseAvailableBalance = decimal.NewFromBigInt(avaiB.BigInt(), int32(-marketInfo.BaseDenomDecimals))
					totalB, _ := decimal.NewFromString(balance.Deposit.TotalBalance)
					marketInfo.BaseTotalBalance = decimal.NewFromBigInt(totalB.BigInt(), int32(-marketInfo.BaseDenomDecimals))
				case marketInfo.QuoteDenom:
					avaiQ, _ := decimal.NewFromString(balance.Deposit.AvailableBalance)
					marketInfo.QuoteAvailableBalance = decimal.NewFromBigInt(avaiQ.BigInt(), int32(-marketInfo.QuoteDenomDecimals))
					totalQ, _ := decimal.NewFromString(balance.Deposit.TotalBalance)
					marketInfo.QuoteTotalBalance = decimal.NewFromBigInt(totalQ.BigInt(), int32(-marketInfo.QuoteDenomDecimals))
				}
			}

			// setting strategy parameter according to inventory conditions
			s.CalculateOverallvalue(marketInfo, s.historySec, &ErrCh)

			if Initial { // initial min pnl's check value when strategy just launched
				marketInfo.MinPnlInitialValue = marketInfo.QuoteTotalBalance
				marketInfo.TimeOfNextUTCDay = TimeOfNextUTCDay()
			} else {
				if time.Now().After(marketInfo.TimeOfNextUTCDay) {
					marketInfo.MinPnlInitialValue = marketInfo.QuoteTotalBalance
					if marketInfo.StopStrategyForDay { // restart the strategy
						marketInfo.StopStrategyForDay = false
					}
				}
			}

			if getAccountErr {
				continue
			}

			bidLen := marketInfo.GetBidOrdersLen()
			askLen := marketInfo.GetAskOrdersLen()

			// risk control part
			if marketInfo.StopStrategy { // if triggered, stop strategy for 10 min
				if time.Now().After(marketInfo.StopStrategyCountDown.Add(time.Second * time.Duration(s.historySec))) {
					marketInfo.StopStrategy = false
				} else {
					s.CancelAllOrders(sender, marketInfo, &ErrCh)
					time.Sleep(time.Second * 10)
					continue
				}
			}
			if marketInfo.StopStrategyForDay {
				s.CancelAllOrders(sender, marketInfo, &ErrCh)
				time.Sleep(time.Second * 10)
				continue
			}
			if time.Now().After(printOrdersTime.Add(time.Second * 5)) {
				s.logger.Infof("%s spot market having %d BUY orders, %d SELL orders\n", marketInfo.Ticker, bidLen, askLen)
				printOrdersTime = time.Now()
			}
			//	if !Initial {
			//		// if all the orders on one side got filled, we have to increase the market volatility for 10 mins
			//		if askLen == 0 || bidLen == 0 {
			//			rollBack = true
			//			rollBackCountDown = time.Now()
			//		}
			//	}
			//	if rollBack && time.Now().After(rollBackCountDown.Add(time.Second*time.Duration(s.historySec))) {
			//		rollBack = false
			//	}
			// for staking window
			//	scale := decimal.NewFromInt(1)
			//	if rollBack {
			//		scale = decimal.NewFromInt(2) // 2 times bigger
			//	}

			scale := decimal.NewFromInt(1)
			// strategy part, need to calculate the staking window.
			marketInfo.CalInventoryPCT()
			marketInfo.CalVolatility(scale)
			marketInfo.ReservationPriceAndSpread(scale)
			bestAskPrice := getPrice(marketInfo.BestAsk, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
			bestBidPrice := getPrice(marketInfo.BestBid, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
			upperPrice := getPrice(marketInfo.UpperBound, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
			lowerPrice := getPrice(marketInfo.LowerBound, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)

			bidLen = marketInfo.GetBidOrdersLen()
			askLen = marketInfo.GetAskOrdersLen()
			bidOrdersmsgs := make([]cosmtypes.Msg, 0, s.spotSideCount)
			askOrdersmsgs := make([]cosmtypes.Msg, 0, s.spotSideCount)
			bidCancelmsgs := make([]cosmtypes.Msg, 0, 10)
			askCancelmsgs := make([]cosmtypes.Msg, 0, 10)

			// best limit order part
			oldBidOrder := marketInfo.GetBidOrder(0)
			oldAskOrder := marketInfo.GetAskOrder(0)

			// cancel ladder limit order part
			if bidLen > 0 {
				wg.Add(1)
				go func() {
					defer wg.Done()
					var canceledOrders []*spotExchangePB.SpotLimitOrder
					if bidLen > s.spotSideCount { // if order num is more than limit, cancel from outside
						canceledOrders = marketInfo.GetNewBidOrdersFromReduce(s)
						for _, order := range canceledOrders {
							msg := &exchangetypes.MsgCancelSpotOrder{
								Sender:       sender.String(),
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							bidCancelmsgs = append(bidCancelmsgs, msg)
						}
					}
					marketInfo.BidOrders.mux.RLock()
					for _, order := range marketInfo.BidOrders.Orders { // if the order is out of the window, cancel it
						orderPrice := cosmtypes.MustNewDecFromStr(order.Price)
						if orderPrice.LT(lowerPrice) || orderPrice.GT(bestBidPrice) || orderPrice.GTE(bestAskPrice) {
							msg := &exchangetypes.MsgCancelSpotOrder{
								Sender:       sender.String(),
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							bidCancelmsgs = append(bidCancelmsgs, msg)
							canceledOrders = append(canceledOrders, order)
						}
					}
					marketInfo.BidOrders.mux.RUnlock()
					marketInfo.CancelBidOrdersFromOrderList(canceledOrders)
				}()
			}
			if askLen > 0 {
				wg.Add(1)
				go func() {
					defer wg.Done()
					var canceledOrders []*spotExchangePB.SpotLimitOrder
					if askLen > s.spotSideCount { // if order num is more than limit, cancel from outside
						canceledOrders = marketInfo.GetNewAskOrdersFromReduce(s)
						for _, order := range canceledOrders {
							msg := &exchangetypes.MsgCancelSpotOrder{
								Sender:       sender.String(),
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							askCancelmsgs = append(askCancelmsgs, msg)
						}
					}
					marketInfo.AskOrders.mux.Lock()
					for _, order := range marketInfo.AskOrders.Orders {
						orderPrice := cosmtypes.MustNewDecFromStr(order.Price)
						if orderPrice.GT(upperPrice) && orderPrice.LT(bestAskPrice) || orderPrice.LTE(bestBidPrice) {
							msg := &exchangetypes.MsgCancelSpotOrder{
								Sender:       sender.String(),
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							askCancelmsgs = append(askCancelmsgs, msg)
							canceledOrders = append(canceledOrders, order)
						}
					}
					marketInfo.AskOrders.mux.Unlock()
					marketInfo.CancelAskOrdersFromOrderList(canceledOrders)
				}()
			}
			wg.Wait()

			// cancel orders part
			cancelOrderMsgs := make([]cosmtypes.Msg, 0, 10)

			var allCanceledOrders int
			bidCancelLen := len(bidCancelmsgs)
			if bidCancelLen != 0 {
				cancelOrderMsgs = append(cancelOrderMsgs, bidCancelmsgs...)
				allCanceledOrders += bidCancelLen
			}
			askCancelLen := len(askCancelmsgs)
			if askCancelLen != 0 {
				cancelOrderMsgs = append(cancelOrderMsgs, askCancelmsgs...)
				allCanceledOrders += askCancelLen
			}

			if allCanceledOrders != 0 {
				s.HandleRequestMsgs(
					"cancel",
					allCanceledOrders,
					cancelOrderMsgs,
					marketInfo,
					&ErrCh,
				)
				// cancel first then place orders
				time.Sleep(time.Second * s.dataCenter.UpdateInterval)
				Initial = false
				continue
			}

			// limit order part
			// decide max order size in coin
			marketInfo.MaxOrderSize = marketInfo.MaxOrderValue.Div(marketInfo.OraclePrice)

			wg.Add(2)
			go func() {
				defer wg.Done()
				// best bid
				var Updating bool = false
				orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "buy", marketInfo.MaxOrderSize)
				if bidLen == 0 {
					Updating = true
				} else {
					oldBestPrice := cosmtypes.MustNewDecFromStr(oldBidOrder.Price)
					tickLevel := marketInfo.MinPriceTickSize.Mul(cosmtypes.NewDec(int64(s.bufferTicks)))
					if bestBidPrice.GT(oldBestPrice.Add(tickLevel)) || bestBidPrice.LT(oldBestPrice) {
						Updating = true
					}
				}
				if Updating && placeOrder {
					price := bestBidPrice
					if marketInfo.CheckNewOrderIsSafe("buy", price, bestAskPrice, bestBidPrice, oldBidOrder, oldAskOrder) {
						order := NewSpotOrder(subaccountID, marketInfo, &SpotOrderData{
							OrderType:    1,
							Price:        price,
							Quantity:     orderSize,
							FeeRecipient: sender.String(),
						})
						msg := &exchangetypes.MsgCreateSpotLimitOrder{
							Sender: sender.String(),
							Order:  *order,
						}
						bidOrdersmsgs = append(bidOrdersmsgs, msg)
						bidLen++
					}
				}
			}()
			go func() {
				defer wg.Done()
				// best ask
				var Updating bool = false
				orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "sell", marketInfo.MaxOrderSize)
				if askLen == 0 {
					Updating = true
				} else {
					oldBestPrice := cosmtypes.MustNewDecFromStr(oldAskOrder.Price)
					tickLevel := marketInfo.MinPriceTickSize.Mul(cosmtypes.NewDec(int64(s.bufferTicks)))
					if bestAskPrice.GT(oldBestPrice) || bestAskPrice.LT(oldBestPrice.Sub(tickLevel)) {
						Updating = true
					}
				}
				if Updating && placeOrder {
					price := bestAskPrice
					if marketInfo.CheckNewOrderIsSafe("sell", price, bestAskPrice, bestBidPrice, oldBidOrder, oldAskOrder) {
						order := NewSpotOrder(subaccountID, marketInfo, &SpotOrderData{
							OrderType:    2,
							Price:        price,
							Quantity:     orderSize,
							FeeRecipient: sender.String(),
						})
						msg := &exchangetypes.MsgCreateSpotLimitOrder{
							Sender: sender.String(),
							Order:  *order,
						}
						askOrdersmsgs = append(askOrdersmsgs, msg)
						askLen++
					}
				}
			}()
			wg.Wait()

			// ladder orders part
			wg.Add(2)
			go func() {
				defer wg.Done()
				var NumNeedToSend int
				if bidLen == 0 {
					return
				}
				if bidLen < s.spotSideCount {
					NumNeedToSend = s.spotSideCount - bidLen
				}
				for idx := 1; idx <= NumNeedToSend; idx++ {
					randNum := decimal.NewFromInt(int64(rand.Intn(80))).Add(decimal.NewFromInt(20)).Div(decimal.NewFromInt(100))  // 0.2~1
					randNumQ := decimal.NewFromInt(int64(rand.Intn(40))).Add(decimal.NewFromInt(60)).Div(decimal.NewFromInt(100)) // 0.6~1
					thickness := marketInfo.BestBid.Sub(marketInfo.LowerBound)
					differ := thickness.Mul(randNum)
					scaledPrice := marketInfo.BestBid.Sub(differ)
					orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "buy", marketInfo.MaxOrderSize.Mul(randNumQ))
					price := getPrice(scaledPrice, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
					if placeOrder && marketInfo.CheckNewOrderIsSafe("buy", price, bestAskPrice, bestBidPrice, oldBidOrder, oldAskOrder) {
						order := NewSpotOrder(subaccountID, marketInfo, &SpotOrderData{
							OrderType:    1,
							Price:        price,
							Quantity:     orderSize,
							FeeRecipient: sender.String(),
						})
						msg := &exchangetypes.MsgCreateSpotLimitOrder{
							Sender: sender.String(),
							Order:  *order,
						}
						bidOrdersmsgs = append(bidOrdersmsgs, msg)
					}
				}
			}()
			go func() {
				defer wg.Done()
				var NumNeedToSend int
				if askLen == 0 {
					return
				}
				if askLen < s.spotSideCount {
					NumNeedToSend = s.spotSideCount - askLen
				}
				for idx := 1; idx <= NumNeedToSend; idx++ {
					randNum := decimal.NewFromInt(int64(rand.Intn(80))).Add(decimal.NewFromInt(20)).Div(decimal.NewFromInt(100))  // 0.2~1
					randNumQ := decimal.NewFromInt(int64(rand.Intn(40))).Add(decimal.NewFromInt(60)).Div(decimal.NewFromInt(100)) // 0.6~1
					thickness := marketInfo.UpperBound.Sub(marketInfo.BestAsk)
					differ := thickness.Mul(randNum)
					scaledPrice := marketInfo.BestAsk.Add(differ)
					orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "sell", marketInfo.MaxOrderSize.Mul(randNumQ))
					price := getPrice(scaledPrice, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
					if placeOrder && marketInfo.CheckNewOrderIsSafe("sell", price, bestAskPrice, bestBidPrice, oldBidOrder, oldAskOrder) {
						order := NewSpotOrder(subaccountID, marketInfo, &SpotOrderData{
							OrderType:    2,
							Price:        price,
							Quantity:     orderSize,
							FeeRecipient: sender.String(),
						})
						msg := &exchangetypes.MsgCreateSpotLimitOrder{
							Sender: sender.String(),
							Order:  *order,
						}
						askOrdersmsgs = append(askOrdersmsgs, msg)
					}
				}
			}()
			wg.Wait()

			// place orders part
			if s.appDown {
				// exit directly without place any order
				return
			}
			ordermsgs := make([]cosmtypes.Msg, 0, s.spotSideCount*2)
			var allOrdersLen int
			bidOrdersLen := len(bidOrdersmsgs)
			if bidOrdersLen != 0 {
				ordermsgs = append(ordermsgs, bidOrdersmsgs...)
				allOrdersLen += bidOrdersLen
			}
			askOrdersLen := len(askOrdersmsgs)
			if askOrdersLen != 0 {
				ordermsgs = append(ordermsgs, askOrdersmsgs...)
				allOrdersLen += askOrdersLen
			}

			s.HandleRequestMsgs(
				"post",
				allOrdersLen,
				ordermsgs,
				marketInfo,
				&ErrCh,
			)

			Initial = false
			time.Sleep(time.Second * s.dataCenter.UpdateInterval)
		}
	}
}
