package trading

import (
	"context"
	"fmt"
	"strings"
	"time"

	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	oraclePB "github.com/InjectiveLabs/sdk-go/exchange/oracle_rpc/pb"
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
	Partial  = "partial_filled"
)

func (s *tradingSvc) StreamInjectiveDerivativeOrderSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s derivative order session.", m.Ticker)
			return
		default:
			s.StreamInjectiveDerivativeOrder(ctx, m, subaccountID, marketInfo)
			message := fmt.Sprintf("Reconnecting %s derivative StreamOrders...", m.Ticker)
			s.logger.Errorln(message)
		}
	}
}

func (s *tradingSvc) StreamInjectiveDerivativeOrder(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	steam, err := s.derivativesClient.StreamOrders(ctx, &derivativeExchangePB.StreamOrdersRequest{
		MarketId:     m.MarketId,
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect derivative StreamTrades for %s with err: %s", m.Ticker, err.Error())
		s.logger.Errorln(message)
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s derivative StreamOrders", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s derivative StreamOrders with err: %s", m.Ticker, err.Error())
				s.logger.Errorln(message)
				return
			}
			go marketInfo.HandleOrder(resp)
		}
	}
}

func (m *DerivativeMarketInfo) HandleOrder(resp *derivativeExchangePB.StreamOrdersResponse) {
	switch strings.ToLower(resp.OperationType) {
	case Insert:
		switch strings.ToLower(resp.Order.State) {
		case Unfilled:
			// insert new limit order
			switch strings.ToLower(resp.Order.OrderSide) {
			case "sell":
				m.InsertAskOrders(resp.Order)
			case "buy":
				m.InsertBidOrders(resp.Order)
			}
		case Booked:
			// mainnet
			switch strings.ToLower(resp.Order.OrderSide) {
			case "sell":
				m.InsertAskOrders(resp.Order)
			case "buy":
				m.InsertBidOrders(resp.Order)
			}
		}
	case Update:
		if strings.ToLower(resp.Order.State) == Canceled {
			// insert new limit order
			switch strings.ToLower(resp.Order.OrderSide) {
			case "sell":
				if m.IsMyAskOrder(resp.Order.OrderHash) {
					m.CancelAskOrdersFromOrderList([]*derivativeExchangePB.DerivativeLimitOrder{resp.Order})
				}
			case "buy":
				if m.IsMyBidOrder(resp.Order.OrderHash) {
					m.CancelBidOrdersFromOrderList([]*derivativeExchangePB.DerivativeLimitOrder{resp.Order})
				}
			}
		} else if strings.ToLower(resp.Order.State) == Partial {
			switch strings.ToLower(resp.Order.OrderSide) {
			case "sell":
				m.UpdateAskOrders(resp.Order)
			case "buy":
				m.UpdateBidOrders(resp.Order)
			}
		}
	default:
		// pass
	}
}

func (s *tradingSvc) StreamInjectiveDerivativeTradeSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s derivative trade session.", m.Ticker)
			return
		default:
			s.StreamInjectiveDerivativeTrade(ctx, m, subaccountID, marketInfo)
			message := fmt.Sprintf("Reconnecting %s derivative StreamTrades...", m.Ticker)
			s.logger.Errorln(message)
		}
	}
}

func (s *tradingSvc) StreamInjectiveDerivativeTrade(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	steam, err := s.derivativesClient.StreamTrades(ctx, &derivativeExchangePB.StreamTradesRequest{
		MarketId:     m.MarketId,
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect derivative StreamTrades for %s with err: %s", m.Ticker, err.Error())
		s.logger.Errorln(message)
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s derivative StreamTrades", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s derivative StreamTrades with err: %s", m.Ticker, err.Error())
				s.logger.Errorln(message)
				return
			}
			go s.HandleTrades(m.Ticker, resp, marketInfo)
		}
	}
}

func (s *tradingSvc) HandleTrades(ticker string, resp *derivativeExchangePB.StreamTradesResponse, marketInfo *DerivativeMarketInfo) {
	if resp == nil {
		return
	}
	data := resp.Trade
	qty, _ := decimal.NewFromString(data.PositionDelta.ExecutionQuantity)
	if qty.IsZero() {
		return
	}
	tradeSide := strings.ToLower(data.PositionDelta.TradeDirection)
	cosPrice, _ := cosmtypes.NewDecFromStr(data.PositionDelta.ExecutionPrice)
	tradePrice := getPriceForPrintOutForDerivative(cosPrice, marketInfo.QuoteDenomDecimals)
	tradeQty, _ := qty.Float64()
	execType := strings.ToLower(data.TradeExecutionType)
	stamp := time.Unix(0, data.ExecutedAt*int64(1000000))

	if tradePrice*tradeQty > 15 {
		message := fmt.Sprintf("%s ✅ %s filled %s derivative order @ %f with %f %s on Inj-Exch", stamp.Format("2006-01-02 15:04:05.999"), execType, tradeSide, tradePrice, tradeQty, ticker)
		s.logger.Infof(message)
	}
}

func (s *tradingSvc) StreamInjectiveDerivativePositionSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s derivative position session.", m.Ticker)
			return
		default:
			s.StreamInjectiveDerivativePositions(ctx, m, subaccountID, marketInfo)
			message := fmt.Sprintf("Reconnecting %s derivative StreamPositions...", m.Ticker)
			s.logger.Errorln(message)
		}
	}
}

func (s *tradingSvc) StreamInjectiveDerivativePositions(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	steam, err := s.derivativesClient.StreamPositions(ctx, &derivativeExchangePB.StreamPositionsRequest{
		MarketId:     m.MarketId,
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect derivative StreamPositions for %s with err: %s", m.Ticker, err.Error())
		s.logger.Errorln(message)
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s derivative StreamPositions", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s derivative StreamPositions with err: %s", m.Ticker, err.Error())
				s.logger.Errorln(message)
				return
			}
			go s.HandlePosition(resp, m.Ticker)
		}
	}
}

func (s *tradingSvc) HandlePosition(resp *derivativeExchangePB.StreamPositionsResponse, ticker string) {
	data := resp.Position
	if data == nil {
		s.DeleteInjectivePosition(ticker)
		return
	}
	if s.IsAlreadyInPositions(data.Ticker) {
		// update position
		s.UpdateInjectivePosition(data)
		return
	}
	// new position
	s.AddNewInjectivePosition(data)
}

func (s *tradingSvc) StreamInjectiveOraclePriceSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, marketInfo *DerivativeMarketInfo) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s oracle price session.", m.Ticker)
			return
		default:
			s.StreamInjectiveOraclePrices(ctx, m, marketInfo)
			message := fmt.Sprintf("Reconnecting %s oracle StreamPrices...", m.Ticker)
			s.logger.Errorln(message)
		}
	}
}

func (s *tradingSvc) StreamInjectiveOraclePrices(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, marketInfo *DerivativeMarketInfo) {
	steam, err := s.oracleClient.StreamPrices(ctx, &oraclePB.StreamPricesRequest{
		BaseSymbol:  marketInfo.OracleBase,
		QuoteSymbol: marketInfo.OracleQuote,
		OracleType:  marketInfo.OracleType.String(),
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect oracle StreamPrices for %s with err: %s", m.Ticker, err.Error())
		s.logger.Errorln(message)
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s oracle StreamPrices", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s oracle StreamPrices with err: %s", m.Ticker, err.Error())
				s.logger.Errorln(message)
				return
			}
			fmt.Println(resp.Price)
		}
	}
}

func (s *tradingSvc) StreamInjectiveDerivativeOrderBookSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	for {
		select {
		case <-ctx.Done():
			s.logger.Infof("Closing %s derivative orderbook session.", m.Ticker)
			return
		default:
			s.StreamInjectiveDerivativeOrderBook(ctx, m, subaccountID, marketInfo)
			message := fmt.Sprintf("Reconnecting %s derivative StreamOrderBook...", m.Ticker)
			s.logger.Errorln(message)
		}
	}
}

func (s *tradingSvc) StreamInjectiveDerivativeOrderBook(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	steam, err := s.derivativesClient.StreamOrderbook(ctx, &derivativeExchangePB.StreamOrderbookRequest{
		MarketIds: []string{m.MarketId},
	})
	if err != nil {
		message := fmt.Sprintf("Fail to connect derivative StreamOrderbook for %s with err: %s", m.Ticker, err.Error())
		s.logger.Errorln(message)
		time.Sleep(time.Second * 10)
		return
	}
	s.logger.Infof("Connected to %s derivative StreamOrderbook", m.Ticker)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			resp, err := steam.Recv()
			if err != nil {
				message := fmt.Sprintf("Closing %s derivative StreamOrderbook with err: %s", m.Ticker, err.Error())
				s.logger.Errorln(message)
				return
			}
			fmt.Println(resp)
		}
	}
}
