package trading

import (
	"bytes"
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
)

func (c *SingleExchangeMM) InitMMStrategy(idx int, marketInfo *SpotMarketInfo, s *tradingSvc) error {
	l := len(c.Exchanges)
	c.Symbol = make([]string, l)
	c.Bids = make([][]interface{}, l)
	c.Asks = make([][]interface{}, l)
	for i, exchange := range c.Exchanges {
		switch exchange {
		case "Binance":
			var buffer bytes.Buffer
			tmp := strings.Split(s.injSymbols[idx], "/")
			buffer.WriteString(tmp[0])
			buffer.WriteString(tmp[1])
			c.Symbol[i] = buffer.String()
		}
	}
	return nil
}

// check the balance before placing order
func (s *tradingSvc) getCorrectOrderSize(m *SpotMarketInfo, method string, qty decimal.Decimal) (formatedQty cosmtypes.Dec, enough bool) {
	// all calculation in quote value , with 2% buffer
	var min decimal.Decimal
	maxOrderValue := m.MaxOrderValue
	formatedQty = cosmtypes.NewDec(0)
	enough = true
	switch strings.ToLower(method) {
	case "buy":
		if m.ReachMaxPosition {
			enough = false
			return formatedQty, enough
		}
		qtyValue := qty.Mul(m.OraclePrice)
		inj := m.QuoteAvailableBalance
		min = decimal.Min(maxOrderValue, qtyValue, inj)

	case "sell":
		qtyValue := qty.Mul(m.OraclePrice)
		inj := m.BaseAvailableBalance.Mul(m.OraclePrice)
		min = decimal.Min(m.MaxOrderValue, qtyValue, inj)
	}
	if enough {
		qty := min.Div(m.OraclePrice)
		formatedQty = getQuantity(qty, m.MinQuantityTickSize, m.BaseDenomDecimals)
	}
	return formatedQty, enough
}

func (s *tradingSvc) AccountMonitorSession(ctx context.Context, marketInfo *SpotMarketInfo, interval time.Duration, ErrCh *chan map[string]interface{}) {
	AccountCheck := time.NewTicker(time.Second * interval)
	defer AccountCheck.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-AccountCheck.C:
			s.logger.Infof("%s MM strategy has %s %s and %s %s.", marketInfo.Ticker, marketInfo.BaseTotalBalance.String(), marketInfo.BaseSymbol, marketInfo.QuoteTotalBalance.String(), marketInfo.QuoteSymbol)

			if !marketInfo.StopStrategyForDay {
				marketInfo.StopStrategyForDay = marketInfo.IsMinPnlOccur()
				if marketInfo.StopStrategyForDay {
					message := fmt.Sprintf("❌ MIN_PNL: %s spot market, stop the strategy for today.", marketInfo.Ticker)
					e := make(map[string]interface{})
					e["critical"] = true
					e["count"] = false
					e["wait"] = 5
					e["message"] = message
					(*ErrCh) <- e
					go s.SendCritialAlertToDiscord(message)
				}
			}
			if !marketInfo.StopStrategy {
				marketInfo.StopStrategy = marketInfo.IsMaxDrawDownOccur()
				if marketInfo.StopStrategy {
					marketInfo.StopStrategyCountDown = time.Now()
					message := fmt.Sprintf("❌ MAX_DD: %s spot market, stop the strategy for 10 min.", marketInfo.Ticker)
					e := make(map[string]interface{})
					e["critical"] = true
					e["count"] = false
					e["wait"] = 5
					e["message"] = message
					(*ErrCh) <- e
					go s.SendCritialAlertToDiscord(message)
				}
			}
		default:
			time.Sleep(time.Second)
		}
	}
}

func (s *tradingSvc) SendTestOrder(ctx context.Context, marketInfo *SpotMarketInfo) {
	if !s.sendSelfOrder {
		return
	}
	marketOrderInterval := 40 * time.Second
	marketOrderTime := time.Now()
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	for {
		if !marketInfo.StopStrategy && !marketInfo.StopStrategyForDay {
			if time.Now().After(marketOrderTime) {
				marketOrderTime = time.Now().Add(marketOrderInterval)
				resp, err := s.spotsClient.Orderbook(ctx, &spotExchangePB.OrderbookRequest{
					MarketId: marketInfo.MarketID.Hex(),
				})

				if err != nil {
					s.logger.Infof("Failed to get orderbook for %s spot market, skipping and will try again in %d seconds.", marketInfo.Ticker, marketOrderInterval)
					continue
				}

				if len(resp.Orderbook.Sells) == 0 {
					s.logger.Infof("No sell orders in %s spot market, skipping and will try again in %d seconds.", marketInfo.Ticker, marketOrderInterval)
					continue
				}

				sellOrder := resp.Orderbook.Sells[0]
				minOrder := decimal.NewFromInt(10).Div(marketInfo.OraclePrice)
				orderSize := getQuantity(minOrder, marketInfo.MinQuantityTickSize, marketInfo.BaseDenomDecimals).Add(marketInfo.MinQuantityTickSize.Mul(cosmtypes.NewDec(5)))
				order := NewSpotOrder(subaccountID, marketInfo, &SpotOrderData{
					OrderType:    exchangetypes.OrderType_BUY,
					Price:        cosmtypes.MustNewDecFromStr(sellOrder.Price),
					Quantity:     orderSize,
					FeeRecipient: sender.String(),
				})

				msg := exchangetypes.MsgCreateSpotMarketOrder{
					Sender: sender.String(),
					Order:  *order,
				}
				s.logger.Infof("🔥 Sending a market buy order in %s spot market", marketInfo.Ticker)

				if _, err := s.cosmosClient.SyncBroadcastMsg(&msg); err != nil {
					s.logger.Errorf("Failed creating order with error %s", err.Error())
				}
			}
		}
		time.Sleep(time.Second)
	}
}

func (c *SingleExchangeMM) GetBidDatas(exchIdx, levelIdx int) (bidPrice decimal.Decimal, bidQty decimal.Decimal) {
	if len(c.Bids) == 0 {
		return bidPrice, bidQty
	}
	exchBids := c.Bids[exchIdx]
	bids, ok := exchBids[levelIdx].([]interface{})
	if ok {
		bidPrice, _ = decimal.NewFromString(bids[0].(string))
		bidQty, _ = decimal.NewFromString(bids[1].(string))
	}
	return bidPrice, bidQty
}

func (c *SingleExchangeMM) GetAskDatas(exchIdx, levelIdx int) (askPrice decimal.Decimal, askQty decimal.Decimal) {
	if len(c.Asks) == 0 {
		return askPrice, askQty
	}
	exch := c.Asks[exchIdx]
	asks, ok := exch[levelIdx].([]interface{})
	if ok {
		askPrice, _ = decimal.NewFromString(asks[0].(string))
		askQty, _ = decimal.NewFromString(asks[1].(string))
	}
	return askPrice, askQty
}

func (s *tradingSvc) SessionErrHandling(e *map[string]interface{}) {
	var wait int = 10 //default wait time is 10 sec
	var IsCritical bool = false
	var message string = "error occured"
	var count bool = false
	sec, ok := (*e)["wait"].(int)
	if ok {
		wait = sec
	}
	crit, ok := (*e)["critical"].(bool)
	if ok {
		IsCritical = crit
	}
	mes, ok := (*e)["message"].(string)
	if ok {
		message = mes
	}
	cc, ok := (*e)["count"].(bool)
	if ok {
		count = cc
	}
	switch IsCritical {
	case true:
		s.logger.Errorln(message)
		if count {
			s.critical.mu.Lock()
			s.critical.Times = append(s.critical.Times, time.Now())
			s.critical.Errs = append(s.critical.Errs, message)
			s.critical.mu.Unlock()
		}
		s.critical.mu.Lock()
		l := len(s.critical.Errs)
		s.critical.mu.Unlock()
		s.logger.Warningf("With %d critical errors within 5 min, over 5 critial errors will shut down the app.", l)
		if l > 5 {
			send := fmt.Sprintf("APP_DOWN: Occured over 5 critical errors in 5 min, please go check it up!")
			s.logger.Errorln(send)
			s.SendCritialAlertToDiscord(send)
			s.PrintOutAllErrs()
			s.Close()
			return
		}
	default:
		s.logger.Warningln(message)
		// pass
	}
	if wait == 0 {
		return
	}
	time.Sleep(time.Second * time.Duration(wait))
}

func (s *tradingSvc) PrintOutAllErrs() {
	for i, err := range s.critical.Errs {
		fmt.Printf("%d. %s : %s \n", i, s.critical.Times[i].Format("2006-01-02T15:04:05.000"), err)
	}
}

func (s *tradingSvc) RenewCriticalErrs() {
	l := len(s.critical.Errs)
	if l == 0 {
		return
	}
	// 5 min moving window to collect critical errors
	var loc int = -1
	for i, st := range s.critical.Times {
		if !time.Now().After(st.Add(time.Second * 300)) {
			continue
		}
		loc = i
	}
	if loc == -1 {
		return
	}
	s.critical.mu.Lock()
	s.critical.Errs = s.critical.Errs[:loc]
	s.critical.Times = s.critical.Times[:loc]
	s.critical.mu.Unlock()
}

func (s *tradingSvc) HandleRequestMsgs(
	method string,
	allRequests int,
	Msgs []cosmtypes.Msg,
	marketInfo *SpotMarketInfo,
	ErrCh *chan map[string]interface{},
) {
	for {
		if allRequests == 0 {
			return
		}
		if res, err := s.cosmosClient.SyncBroadcastMsg(Msgs...); err != nil {
			if strings.Contains(err.Error(), "order doesnt exist") {
				tmp := strings.Split(err.Error(), ":")
				idxStr := strings.Replace(tmp[3], " ", "", -1)
				idx, err := strconv.Atoi(idxStr)
				if err != nil {
					// handle
				}
				// remove error msg from msg list
				Msgs = append(Msgs[:idx], Msgs[idx+1:]...)
				allRequests--
				continue
			}
			messageIdx := 2
			var buffer bytes.Buffer
			buffer.WriteString(marketInfo.Ticker)
			buffer.WriteString(" spot market: ")
			if allRequests != 0 {
				resStr := ""
				if res != nil {
					resStr = res.String()
				}
				message := fmt.Sprintf("Fail to %s %d orders (%s)", method, allRequests, resStr)
				buffer.WriteString(message)
			}
			buffer.WriteString("with err: ")
			buffer.WriteString(err.Error())
			buffer.WriteString("\n")
			message := buffer.String()
			e := make(map[string]interface{})
			e["critical"] = true
			e["count"] = true
			e["wait"] = 5
			e["message"] = message
			(*ErrCh) <- e
			if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
				go s.SendCritialAlertToDiscord(message)
				marketInfo.LastSendMessageTime[messageIdx] = time.Now()
			}
		} else {
			var buffer bytes.Buffer
			buffer.WriteString(marketInfo.Ticker)
			buffer.WriteString(" spot market: ")
			if allRequests != 0 {
				var message string
				switch method {
				case "cancel":
					message = fmt.Sprintf("🗑 canceled %v orders.", allRequests)
				case "post":
					message = fmt.Sprintf("🔥 posted %v orders.", allRequests)
				}
				buffer.WriteString(message)
			}
			s.logger.Infoln(buffer.String())
		}
		return
	}
}

func (s *tradingSvc) HandleOrdersCancelingWhenAppClose(
	allCanceledOrders int,
	cancelOrderMsgs []cosmtypes.Msg,
	ticker string,
) {
	for {
		if allCanceledOrders == 0 {
			return
		}
		if res, err := s.cosmosClient.SyncBroadcastMsg(cancelOrderMsgs...); err != nil {
			if strings.Contains(err.Error(), "order doesnt exist") {
				tmp := strings.Split(err.Error(), ":")
				idxStr := strings.Replace(tmp[3], " ", "", -1)
				idx, err := strconv.Atoi(idxStr)
				if err != nil {
					// handle
				}
				// remove error msg from msg list
				cancelOrderMsgs = append(cancelOrderMsgs[:idx], cancelOrderMsgs[idx+1:]...)
				allCanceledOrders--
				continue
			}
			var buffer bytes.Buffer
			buffer.WriteString(ticker)
			buffer.WriteString(" spot market: ")
			if allCanceledOrders != 0 {
				resStr := ""
				if res != nil {
					resStr = res.String()
				}
				message := fmt.Sprintf("Fail to cancel %d orders (%s)", allCanceledOrders, resStr)
				buffer.WriteString(message)
			}
			buffer.WriteString("with err: ")
			buffer.WriteString(err.Error())
			buffer.WriteString("\n")
			message := buffer.String()
			s.logger.Infoln(message)
			go s.SendCritialAlertToDiscord(message)
		} else {
			var buffer bytes.Buffer
			buffer.WriteString(ticker)
			buffer.WriteString(" spot market: ")
			if allCanceledOrders != 0 {
				message := fmt.Sprintf("🗑 Cancelled %v orders.", allCanceledOrders)
				buffer.WriteString(message)
			}
			s.logger.Infoln(buffer.String())
		}
		return
	}
}

func (s *tradingSvc) CancelAllOrders(sender cosmtypes.AccAddress, m *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	msgs := make([]cosmtypes.Msg, 0)
	m.BidOrders.mux.RLock()
	for _, order := range m.BidOrders.Orders {
		msg := &exchangetypes.MsgCancelSpotOrder{
			Sender:       sender.String(),
			MarketId:     order.MarketId,
			SubaccountId: order.SubaccountId,
			OrderHash:    order.OrderHash,
		}
		msgs = append(msgs, msg)
	}
	m.BidOrders.mux.RUnlock()

	m.AskOrders.mux.RLock()
	for _, order := range m.AskOrders.Orders {
		msg := &exchangetypes.MsgCancelSpotOrder{
			Sender:       sender.String(),
			MarketId:     order.MarketId,
			SubaccountId: order.SubaccountId,
			OrderHash:    order.OrderHash,
		}
		msgs = append(msgs, msg)
	}
	m.AskOrders.mux.RUnlock()

	if len(msgs) == 0 {
		return
	}
	s.HandleRequestMsgs("cancel", len(msgs), msgs, m, ErrCh)
}
