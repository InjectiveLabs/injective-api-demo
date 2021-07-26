package trading

import (
	"context"
	"strings"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	accountsPB "github.com/InjectiveLabs/sdk-go/exchange/accounts_rpc/pb"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	oraclePB "github.com/InjectiveLabs/sdk-go/exchange/oracle_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/tendermint/tendermint/libs/rand"
)

func (s *tradingSvc) PostDerivativeLimitOrders(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo) {
	marketInfo := DerivativeMarketToMarketInfo(m)
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)

	tradingCycleSleepTime := 10 * time.Second

	for {
		priceReq := &oraclePB.PriceRequest{
			BaseSymbol:        marketInfo.OracleBase,
			QuoteSymbol:       marketInfo.OracleQuote,
			OracleType:        marketInfo.OracleType.String(),
			OracleScaleFactor: marketInfo.OracleScaleFactor,
		}
		price, err := s.oracleClient.Price(ctx, priceReq)

		if err != nil || price == nil {
			s.logger.Errorf("Couldn't fetch price for oracle base %s quote %s type %s. Trying again in %d seconds", marketInfo.OracleBase, marketInfo.OracleQuote, string(marketInfo.OracleType), int(tradingCycleSleepTime.Seconds()))
			time.Sleep(tradingCycleSleepTime)
			continue
		}

		marketInfo.MarkPrice, _ = cosmtypes.NewDecFromStr(price.Price)

		for _, orderType := range []exchangetypes.OrderType{exchangetypes.OrderType_BUY, exchangetypes.OrderType_SELL} {
			resp, err := s.accountsClient.SubaccountOrderSummary(ctx, &accountsPB.SubaccountOrderSummaryRequest{
				SubaccountId:   subaccountID.Hex(),
				MarketId:       m.MarketId,
				OrderDirection: strings.ToLower(orderType.String()),
			})
			if err != nil {
				s.logger.Infof("Skipping posting %s orders for %s since got error while fetching subaccount order count %s", orderType.String(), marketInfo.Ticker, err.Error())
				continue
			} else if resp.DerivativeOrdersTotal >= DerivativeBookSideOrderCount {
				s.logger.Infof("Skipping posting %s orders for %s since subaccount already has %d %s orders", orderType.String(), marketInfo.Ticker, resp.DerivativeOrdersTotal, orderType.String())
				time.Sleep(5 * time.Second)
				continue
			}

			msgs := make([]cosmtypes.Msg, 0)

			ordersCount := DerivativeBookSideOrderCount + 1 - int(resp.DerivativeOrdersTotal)

			for idx := 1; idx <= ordersCount; idx++ {

				var price cosmtypes.Dec
				randNum := cosmtypes.NewDec(int64(rand.Intn(100))).Quo(cosmtypes.NewDec(1000))
				if orderType == exchangetypes.OrderType_BUY {
					// 1 - (idx / 400) + randNum
					scaleFactor := cosmtypes.OneDec().Sub(cosmtypes.NewDec(int64(idx)).Quo(cosmtypes.NewDec(200))).Add(randNum)
					price = marketInfo.MarkPrice.Mul(scaleFactor)
				} else {
					// 1 + (idx / 400) - randNum
					scaleFactor := cosmtypes.OneDec().Add(cosmtypes.NewDec(int64(idx)).Quo(cosmtypes.NewDec(200))).Sub(randNum)
					price = marketInfo.MarkPrice.Mul(scaleFactor)
				}
				price = formatToTickSize(price, marketInfo.MinPriceTickSize)

				quantity := marketInfo.MinQuantityTickSize.Mul(cosmtypes.NewDec(int64(idx * 100)))

				//fmt.Println("price", price.String(), "quantity", quantity.String(), "margin", price.Mul(quantity).String())
				order := NewDerivativeOrder(subaccountID, marketInfo, &DerivativeOrderData{
					OrderType:    orderType,
					Price:        price,
					Quantity:     quantity,
					Margin:       price.Mul(quantity),
					FeeRecipient: sender.String(),
				})
				//fmt.Printf("price %s margin %s quantity %s\n", price.String(), price.Mul(quantity).String(), quantity.String())

				msg := &exchangetypes.MsgCreateDerivativeLimitOrder{
					Sender: sender.String(),
					Order:  *order,
				}

				msgs = append(msgs, msg)
			}

			if len(msgs) > 0 {
				if _, err := s.cosmosClient.SyncBroadcastMsg(msgs...); err != nil {
					s.logger.Errorf("❌ Failed creating %s derivative limit orders for %s", orderType.String(), marketInfo.Ticker)
				} else {
					s.logger.Infof("✅ Posted %d %s orders for derivative market %s", len(msgs), orderType.String(), marketInfo.Ticker)
				}
			} else {
				s.logger.Infof("No %s orders to post orders for %s", orderType.String(), marketInfo.Ticker)
			}
		}

		time.Sleep(tradingCycleSleepTime)
	}

}

func (s *tradingSvc) CancelDerivativeLimitOrders(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo) {
	marketInfo := DerivativeMarketToMarketInfo(m)
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)

	cancelCycleSleepTime := 60 * time.Second

	for {
		priceReq := &oraclePB.PriceRequest{
			BaseSymbol:        marketInfo.OracleBase,
			QuoteSymbol:       marketInfo.OracleQuote,
			OracleType:        marketInfo.OracleType.String(),
			OracleScaleFactor: marketInfo.OracleScaleFactor,
		}
		price, err := s.oracleClient.Price(ctx, priceReq)

		if err != nil || price == nil {
			s.logger.Errorf("Couldn't fetch price for oracle base %s quote %s type %s. Trying again in %d seconds", marketInfo.OracleBase, marketInfo.OracleQuote, string(marketInfo.OracleType), int(cancelCycleSleepTime.Seconds()))
			time.Sleep(cancelCycleSleepTime)
			continue
		}

		marketInfo.MarkPrice, _ = cosmtypes.NewDecFromStr(price.Price)

		resp, err := s.derivativesClient.Orders(ctx, &derivativeExchangePB.OrdersRequest{
			SubaccountId: subaccountID.Hex(),
			MarketId:     m.MarketId,
		})
		if err != nil {
			s.logger.Infof("Skipping cancelling orders for %s since got error while fetching subaccount order count %s", marketInfo.Ticker, err.Error())
			continue
		} else if len(resp.Orders) == 0 {
			s.logger.Infof("Skipping cancelling orders for %s since subaccount already has no orders", marketInfo.Ticker)
			time.Sleep(30 * time.Second)
			continue
		}

		msgs := make([]cosmtypes.Msg, 0)

		for _, order := range resp.Orders {
			upperBound := marketInfo.MarkPrice.MulInt64(11).QuoInt64(10)
			lowerBound := marketInfo.MarkPrice.MulInt64(9).QuoInt64(10)

			orderPrice := cosmtypes.MustNewDecFromStr(order.Price)
			if order.OrderType == "sell" && orderPrice.GTE(upperBound) || order.OrderType == "buy" && orderPrice.LTE(lowerBound){
				msg := &exchangetypes.MsgCancelDerivativeOrder{
					Sender:       sender.String(),
					MarketId:     m.MarketId,
					SubaccountId: subaccountID.Hex(),
					OrderHash:    order.OrderHash,
				}

				msgs = append(msgs, msg)
			}
		}

		if len(msgs) > 0 {
			if _, err := s.cosmosClient.SyncBroadcastMsg(msgs...); err != nil {
				s.logger.Errorf("❌ Failed cancelling derivative limit orders for %s", marketInfo.Ticker)
			} else {
				s.logger.Infof("🗑 Cancelled %d orders for derivative market %s", len(msgs), marketInfo.Ticker)
			}
		} else {
			s.logger.Infof("No derivative limit orders to post orders for %s", marketInfo.Ticker)
		}

		time.Sleep(cancelCycleSleepTime)
	}

}
