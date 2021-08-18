package trading

import (
	"context"
	"fmt"
	"strings"
	"time"

	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
	"github.com/shopspring/decimal"
)

// stream key words
const (
	Insert   = "insert"
	Update   = "update"
	Unfilled = "unfilled"
	Booked   = "booked"
	Canceled = "canceled"
)

func (s *tradingSvc) StreamInjectiveSpotOrderSession(ctx context.Context, m *spotExchangePB.SpotMarketInfo, subaccountID *common.Hash, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s spot order session.", m.Ticker)
			s.appDown = true
			return
		default:
			s.StreamInjectiveSpotOrder(ctx, m, subaccountID, marketInfo, ErrCh)
			message := fmt.Sprintf("Reconnecting %s spot StreamOrders...", m.Ticker)
			e := make(map[string]interface{})
			e["critical"] = false
			e["count"] = false
			e["wait"] = 3
			e["message"] = message
			(*ErrCh) <- e
		}
	}
}

func (s *tradingSvc) StreamInjectiveSpotOrder(ctx context.Context, m *spotExchangePB.SpotMarketInfo, subaccountID *common.Hash, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	steam, err := s.spotsClient.StreamOrders(ctx, &spotExchangePB.StreamOrdersRequest{
		MarketId:     m.MarketId,
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect spot streamTrades for %s with err: %s", m.Ticker, err.Error())
		e := make(map[string]interface{})
		e["critical"] = true
		e["count"] = true
		e["wait"] = 12
		e["message"] = message
		(*ErrCh) <- e
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s spot StreamOrders", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			s.appDown = true
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s spot StreamOrders with err: %s", m.Ticker, err.Error())
				e := make(map[string]interface{})
				e["critical"] = false
				e["count"] = false
				e["wait"] = 0
				e["message"] = message
				(*ErrCh) <- e
				return
			}
			go marketInfo.HandleOrder(resp)
		}
	}
}

func (m *SpotMarketInfo) HandleOrder(resp *spotExchangePB.StreamOrdersResponse) {
	switch strings.ToLower(resp.OperationType) {
	case Insert:
		switch strings.ToLower(resp.Order.State) {
		case Unfilled:
			// insert new limit order
			switch strings.ToLower(resp.Order.OrderType) {
			case "sell":
				m.InsertAskOrders([]*spotExchangePB.SpotLimitOrder{resp.Order})
			case "buy":
				m.InsertBidOrders([]*spotExchangePB.SpotLimitOrder{resp.Order})
			}
		case Booked:
			// mainnet
			switch strings.ToLower(resp.Order.OrderType) {
			case "sell":
				m.InsertAskOrders([]*spotExchangePB.SpotLimitOrder{resp.Order})
			case "buy":
				m.InsertBidOrders([]*spotExchangePB.SpotLimitOrder{resp.Order})
			}
		}
	case Update:
		if strings.ToLower(resp.Order.State) == Canceled {
			// insert new limit order
			switch strings.ToLower(resp.Order.OrderType) {
			case "sell":
				if m.IsMyAskOrder(resp.Order.OrderHash) {
					m.CancelAskOrdersFromOrderList([]*spotExchangePB.SpotLimitOrder{resp.Order})
				}
			case "buy":
				if m.IsMyBidOrder(resp.Order.OrderHash) {
					m.CancelBidOrdersFromOrderList([]*spotExchangePB.SpotLimitOrder{resp.Order})
				}
			}
		}
	default:
		// pass
	}
}

func (s *tradingSvc) StreamInjectiveSpotTradeSession(ctx context.Context, m *spotExchangePB.SpotMarketInfo, subaccountID *common.Hash, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s spot trade session.", m.Ticker)
			s.appDown = true
			return
		default:
			s.StreamInjectiveSpotTrade(ctx, m, subaccountID, marketInfo, ErrCh)
			message := fmt.Sprintf("Reconnecting %s spot StreamTrades...", m.Ticker)
			e := make(map[string]interface{})
			e["critical"] = false
			e["count"] = false
			e["wait"] = 3
			e["message"] = message
			(*ErrCh) <- e
		}
	}
}

func (s *tradingSvc) StreamInjectiveSpotTrade(ctx context.Context, m *spotExchangePB.SpotMarketInfo, subaccountID *common.Hash, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	steam, err := s.spotsClient.StreamTrades(ctx, &spotExchangePB.StreamTradesRequest{
		MarketId:     m.MarketId,
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect spot streamTrades for %s with err: %s", m.Ticker, err.Error())
		e := make(map[string]interface{})
		e["critical"] = true
		e["count"] = true
		e["wait"] = 12
		e["message"] = message
		(*ErrCh) <- e
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s spot StreamTrades", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			s.appDown = true
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s spot StreamTrades with err: %s", m.Ticker, err.Error())
				e := make(map[string]interface{})
				e["critical"] = false
				e["count"] = false
				e["wait"] = 0
				e["message"] = message
				(*ErrCh) <- e
				return
			}

			go s.HandleTrades(m.Ticker, resp, marketInfo, ErrCh)
		}
	}
}

type InjPart struct {
	execType   string
	tradeSide  string
	tradePrice float64
	tradeQty   float64
	timeStamp  time.Time
}

func (s *tradingSvc) HandleTrades(ticker string, resp *spotExchangePB.StreamTradesResponse, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	if resp == nil {
		return
	}
	data := resp.Trade
	qty, _ := decimal.NewFromString(data.Price.Quantity)
	if qty.IsZero() {
		return
	}
	tradeSide := strings.ToLower(data.TradeDirection)
	cosPrice, _ := cosmtypes.NewDecFromStr(data.Price.Price)
	tradePrice := getPriceForPrintOut(cosPrice, marketInfo.BaseDenomDecimals, marketInfo.QuoteDenomDecimals)
	tradeQty, _ := decimal.NewFromBigInt(qty.BigInt(), int32(-marketInfo.BaseDenomDecimals)).Float64()
	execType := strings.ToLower(data.TradeExecutionType)
	//stamp := time.Unix(0, data.Price.Timestamp*int64(1000000))

	message := fmt.Sprintf("✅ %s filled %s spot order @ %f with %f %s on Inj-Exch", execType, tradeSide, tradePrice, tradeQty, ticker)
	s.logger.Infof(message)
	go s.SendRegularInfoToDiscord(message)
}
