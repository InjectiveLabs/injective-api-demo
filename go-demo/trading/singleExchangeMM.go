package trading

import (
	"bytes"
	"context"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
	"github.com/tendermint/tendermint/libs/rand"
)

func (s *tradingSvc) SingleExchangeMM(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, idx int, interval time.Duration) {
	s.logger.Infof("✅ Start strategy for %s derivative market.", m.Ticker)
	var Initial bool = true
	var wg sync.WaitGroup
	var printOrdersTime time.Time

	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	marketInfo := DerivativeMarketToMarketInfo(m)
	// set max order value from .env
	marketInfo.MaxOrderValue = decimal.NewFromInt(int64(s.maxOrderValue[idx]))

	buffTickLevel := marketInfo.MinPriceTickSize.Mul(cosmtypes.NewDec(int64(10)))

	marketInfo.LastSendMessageTime = make([]time.Time, 4) // depends on how many critical alerts wanna send with 10 min interval
	// inj stream trades session
	go s.StreamInjectiveDerivativeTradeSession(ctx, m, &subaccountID, marketInfo)
	// inj stream orders session
	//go s.StreamInjectiveDerivativeOrderSession(ctx, m, &subaccountID, marketInfo, ErrCh)
	// inj stream position session
	go s.StreamInjectiveDerivativePositionSession(ctx, m, &subaccountID, marketInfo)
	// inital orders snapshot first
	//s.InitialOrderList(ctx, m, &subaccountID, marketInfo, ErrCh)
	// oracle price session
	go marketInfo.OraclePriceSession(ctx, idx, s, m)

	for {
		select {
		case <-ctx.Done():
			return
		default:
			// check oracle price part
			if !marketInfo.OracleReady {
				message := fmt.Sprintf("Wait 5 sec for connecting reference price")
				s.logger.Errorln(message)
				time.Sleep(time.Second * 5)
				continue
			}
			// initial orders
			s.InitialOrderList(ctx, m, &subaccountID, marketInfo)

			scale := decimal.NewFromInt(1)
			// strategy part, need to calculate the staking window.
			marketInfo.CalVolatility(scale)
			marketInfo.ReservationPriceAndSpread()
			bestAskPrice := getPriceForDerivative(marketInfo.BestAsk, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
			bestBidPrice := getPriceForDerivative(marketInfo.BestBid, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)

			bidLen := marketInfo.GetBidOrdersLen()
			askLen := marketInfo.GetAskOrdersLen()

			if time.Now().After(printOrdersTime.Add(time.Second*5)) && marketInfo.IsOrderUpdated() {
				var buffer bytes.Buffer
				buffer.WriteString(marketInfo.Ticker)
				buffer.WriteString(" having ")
				buffer.WriteString(strconv.Itoa(bidLen))
				buffer.WriteString(" BUY orders, ")
				buffer.WriteString(strconv.Itoa(askLen))
				buffer.WriteString(" SELL orders\n")
				space := strings.Repeat(" ", 30)
				buffer.WriteString(space)
				buffer.WriteString("reservated diff: ")
				diff := marketInfo.ReservedPrice.Sub(marketInfo.OraclePrice).Round(2)
				buffer.WriteString(diff.String())
				buffer.WriteString(", spread: ")
				spread := marketInfo.BestAsk.Sub(marketInfo.BestBid).Div(marketInfo.BestBid).Mul(decimal.NewFromInt(100)).Round(4)
				buffer.WriteString(spread.String())
				buffer.WriteString("%,\n")
				buffer.WriteString(space)
				switch marketInfo.PositionDirection {
				case "null":
					buffer.WriteString("no position.")
				default:
					buffer.WriteString(marketInfo.PositionDirection)
					buffer.WriteString(" ")
					buffer.WriteString(marketInfo.PositionQty.String())
					buffer.WriteString("(")
					buffer.WriteString(marketInfo.MarginValue.Round(2).String())
					buffer.WriteString("USD)")
				}
				s.logger.Infoln(buffer.String())
				printOrdersTime = time.Now()
			}

			// best limit order part
			bidOrdersmsgs := make([]exchangetypes.DerivativeOrder, 0, 1)
			askOrdersmsgs := make([]exchangetypes.DerivativeOrder, 0, 1)
			oldBidOrder := marketInfo.GetBidOrder(0)
			oldAskOrder := marketInfo.GetAskOrder(0)

			// cancel ladder limit order part
			bidCancelmsgs := make([]exchangetypes.OrderData, 0, 10)
			askCancelmsgs := make([]exchangetypes.OrderData, 0, 10)

			if bidLen > 0 {
				wg.Add(1)
				go func() {
					defer wg.Done()
					var canceledOrders []*derivativeExchangePB.DerivativeLimitOrder
					for _, order := range canceledOrders {
						data := exchangetypes.OrderData{
							MarketId:     m.MarketId,
							SubaccountId: subaccountID.Hex(),
							OrderHash:    order.OrderHash,
						}
						bidCancelmsgs = append(bidCancelmsgs, data)
					}
					marketInfo.BidOrders.mux.RLock()
					for _, order := range marketInfo.BidOrders.Orders { // if the order is out of the window, cancel it
						orderPrice := cosmtypes.MustNewDecFromStr(order.Price)
						if orderPrice.LT(bestBidPrice.Sub(buffTickLevel)) || orderPrice.Add(marketInfo.MinPriceTickSize).GT(bestBidPrice) || orderPrice.Add(buffTickLevel).GTE(bestAskPrice) {
							data := exchangetypes.OrderData{
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							bidCancelmsgs = append(bidCancelmsgs, data)
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
					var canceledOrders []*derivativeExchangePB.DerivativeLimitOrder
					for _, order := range canceledOrders {
						data := exchangetypes.OrderData{
							MarketId:     m.MarketId,
							SubaccountId: subaccountID.Hex(),
							OrderHash:    order.OrderHash,
						}
						askCancelmsgs = append(askCancelmsgs, data)
					}
					marketInfo.AskOrders.mux.Lock()
					for _, order := range marketInfo.AskOrders.Orders {
						orderPrice := cosmtypes.MustNewDecFromStr(order.Price)
						if orderPrice.GT(bestAskPrice.Add(buffTickLevel)) && orderPrice.Sub(marketInfo.MinPriceTickSize).LT(bestAskPrice) || orderPrice.Sub(buffTickLevel).LTE(bestBidPrice) {
							data := exchangetypes.OrderData{
								MarketId:     m.MarketId,
								SubaccountId: subaccountID.Hex(),
								OrderHash:    order.OrderHash,
							}
							askCancelmsgs = append(askCancelmsgs, data)
							canceledOrders = append(canceledOrders, order)
						}
					}
					marketInfo.AskOrders.mux.Unlock()
					marketInfo.CancelAskOrdersFromOrderList(canceledOrders)
				}()
			}
			wg.Wait()

			// cancel orders part
			cancelOrderMsgs := &exchangetypes.MsgBatchCancelDerivativeOrders{
				Sender: sender.String(),
			}
			var allCanceledOrders int
			bidCancelLen := len(bidCancelmsgs)
			if bidCancelLen != 0 {
				cancelOrderMsgs.Data = append(cancelOrderMsgs.Data, bidCancelmsgs...)
				allCanceledOrders += bidCancelLen
			}
			askCancelLen := len(askCancelmsgs)
			if askCancelLen != 0 {
				cancelOrderMsgs.Data = append(cancelOrderMsgs.Data, askCancelmsgs...)
				allCanceledOrders += askCancelLen

			}

			if allCanceledOrders != 0 {
				if !marketInfo.IsOrderUpdated() {
					if Initial {
						Initial = false
					}
					time.Sleep(time.Millisecond * s.dataCenter.UpdateInterval)
					continue
				}
				s.HandleRequestMsgs(
					"cancel",
					allCanceledOrders,
					cancelOrderMsgs,
					marketInfo,
				)
				// cancel first then place orders
				if Initial {
					Initial = false
				}
				time.Sleep(time.Millisecond * s.dataCenter.UpdateInterval)
				continue
			}

			if err := s.GetTopOfBook(ctx, m, marketInfo); err != nil {
				message := fmt.Sprintf("Wait 5 sec for getting injective orderbook")
				s.logger.Errorln(message)
				time.Sleep(time.Second * 5)
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
				bidLen = marketInfo.GetBidOrdersLen()
				switch {
				case bidLen == 0:
					Updating = true
				default:
					oldBestPrice := cosmtypes.MustNewDecFromStr(oldBidOrder.Price)
					if bestBidPrice.GT(oldBestPrice.Add(buffTickLevel)) || bestBidPrice.LT(oldBestPrice) {
						Updating = true
					}
				}
				randNumQ := decimal.NewFromInt(int64(rand.Intn(40))).Add(decimal.NewFromInt(60)).Div(decimal.NewFromInt(100)) // 0.6~1
				orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "buy", marketInfo.MaxOrderSize.Mul(randNumQ))
				if Updating && placeOrder {
					price := bestBidPrice
					uplimit := bestAskPrice
					if marketInfo.CheckNewOrderIsSafe("buy", price, uplimit, bestBidPrice, oldBidOrder, oldAskOrder) {
						if !marketInfo.TopAskPrice.IsZero() && price.GT(marketInfo.TopAskPrice) {
							price = marketInfo.TopAskPrice
						}
						order := NewDerivativeOrder(subaccountID, marketInfo, &DerivativeOrderData{
							OrderType:    1,
							Price:        price,
							Quantity:     orderSize,
							Margin:       price.Mul(orderSize).Quo(cosmtypes.NewDec(int64(2))),
							FeeRecipient: sender.String(),
						})
						bidOrdersmsgs = append(bidOrdersmsgs, *order)
						bidLen++
					}
				}
			}()
			go func() {
				defer wg.Done()
				// best ask
				var Updating bool = false
				askLen = marketInfo.GetAskOrdersLen()
				switch {
				case askLen == 0:
					Updating = true
				default:
					oldBestPrice := cosmtypes.MustNewDecFromStr(oldAskOrder.Price)
					if bestAskPrice.GT(oldBestPrice) || bestAskPrice.LT(oldBestPrice.Sub(buffTickLevel)) {
						Updating = true
					}
				}
				randNumQ := decimal.NewFromInt(int64(rand.Intn(40))).Add(decimal.NewFromInt(60)).Div(decimal.NewFromInt(100)) // 0.6~1
				orderSize, placeOrder := s.getCorrectOrderSize(marketInfo, "sell", marketInfo.MaxOrderSize.Mul(randNumQ))
				if Updating && placeOrder {
					price := bestAskPrice
					lowlimit := bestBidPrice
					if marketInfo.CheckNewOrderIsSafe("sell", price, bestAskPrice, lowlimit, oldBidOrder, oldAskOrder) {
						if !marketInfo.TopBidPrice.IsZero() && price.LT(marketInfo.TopBidPrice) {
							price = marketInfo.TopBidPrice
						}
						order := NewDerivativeOrder(subaccountID, marketInfo, &DerivativeOrderData{
							OrderType:    2,
							Price:        price,
							Quantity:     orderSize,
							Margin:       price.Mul(orderSize).Quo(cosmtypes.NewDec(int64(2))),
							FeeRecipient: sender.String(),
						})
						askOrdersmsgs = append(askOrdersmsgs, *order)
						askLen++
					}
				}
			}()
			wg.Wait()

			// place orders part
			ordermsgs := &exchangetypes.MsgBatchCreateDerivativeLimitOrders{
				Sender: sender.String(),
			}
			var allOrdersLen int
			bidOrdersLen := len(bidOrdersmsgs)
			if bidOrdersLen != 0 {
				ordermsgs.Orders = append(ordermsgs.Orders, bidOrdersmsgs...)
				allOrdersLen += bidOrdersLen
			}
			askOrdersLen := len(askOrdersmsgs)
			if askOrdersLen != 0 {
				ordermsgs.Orders = append(ordermsgs.Orders, askOrdersmsgs...)
				allOrdersLen += askOrdersLen
			}
			if allOrdersLen != 0 {
				if !marketInfo.IsOrderUpdated() {
					if Initial {
						Initial = false
					}
					time.Sleep(time.Millisecond * s.dataCenter.UpdateInterval)
					continue
				}
				s.HandleRequestMsgs(
					"post",
					allOrdersLen,
					ordermsgs,
					marketInfo,
				)
			}

			if Initial {
				Initial = false
			}
			time.Sleep(time.Millisecond * s.dataCenter.UpdateInterval)
		}
	}
}
