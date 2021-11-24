package trading

import (
	"context"
	"math"
	"time"

	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	oraclePB "github.com/InjectiveLabs/sdk-go/exchange/oracle_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
)

func (marketInfo *DerivativeMarketInfo) OraclePriceSession(ctx context.Context, idx int, s *tradingSvc, m *derivativeExchangePB.DerivativeMarketInfo) {
	var oracle decimal.Decimal
	marketInfo.OracleReady = false
	oracleCheck := time.NewTicker(time.Second * 5)
	defer oracleCheck.Stop()
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-oracleCheck.C:
				if resp, err := s.oracleClient.Price(ctx, &oraclePB.PriceRequest{
					BaseSymbol:  marketInfo.OracleBase,
					QuoteSymbol: marketInfo.OracleQuote,
					OracleType:  marketInfo.OracleType.String(),
				}); err == nil {
					oracle, err = decimal.NewFromString(resp.Price)
					if err != nil {
						oracle = decimal.NewFromInt(0)
						continue
					}
					if !marketInfo.OracleReady {
						marketInfo.OracleReady = true
					}
					go s.RealTimeChecking(ctx, idx, m, marketInfo)
					marketInfo.OraclePrice = oracle
					marketInfo.CosmOraclePrice = getPriceForDerivative(marketInfo.OraclePrice, marketInfo.QuoteDenomDecimals, marketInfo.MinPriceTickSize)
				}
			default:
				time.Sleep(time.Second)
			}
		}
	}()
}

// basic as model for market making
func (m *DerivativeMarketInfo) ReservationPriceAndSpread() {
	//r(s,t) = s - q * gamma * sigma**2 * (T-t)
	//spread[t] = gamma * (sigma **2) + (2/gamma) * math.log(1 + (gamma/k))
	T := 1.0 // T-t  set it 1 for 24hrs trading market, considering the risk more
	dT := decimal.NewFromFloat(T)
	dgamma := decimal.NewFromFloat(m.RiskAversion)
	dsigma := m.MarketVolatility
	sigma2 := dsigma.Pow(decimal.NewFromFloat(2))
	m.ReservedPrice = m.OraclePrice.Sub(m.InventoryPCT.Mul(dgamma).Mul(sigma2).Mul(dT))

	logpart := decimal.NewFromFloat(math.Log((1 + (m.RiskAversion / m.FillIndensity))))
	first := dgamma.Mul(sigma2)
	second := decimal.NewFromFloat(2).Div(dgamma)
	m.OptSpread = first.Add(second.Mul(logpart))

	halfspread := m.OptSpread.Div(decimal.NewFromFloat(2))
	m.BestAsk = m.ReservedPrice.Add(halfspread)
	m.BestBid = m.ReservedPrice.Sub(halfspread)
}

func (m *DerivativeMarketInfo) CalVolatility(scale decimal.Decimal) {
	m.MarketVolatility = decimal.NewFromFloat(0.01)
}

// set 100k as max position value
func (m *DerivativeMarketInfo) CalInventoryPCT(positionMargin decimal.Decimal) {
	var scale decimal.Decimal
	switch m.PositionDirection {
	case "long":
		scale = decimal.NewFromInt(1)
	case "short":
		scale = decimal.NewFromInt(-1)
	}
	m.InventoryPCT = positionMargin.Mul(scale).Div(decimal.NewFromInt(100000))
}

func (s *tradingSvc) RealTimeChecking(ctx context.Context, idx int, m *derivativeExchangePB.DerivativeMarketInfo, marketInfo *DerivativeMarketInfo) {
	position := s.GetInjectivePositionData(m.Ticker)
	switch {
	case position == nil:
		// no position
		marketInfo.PositionQty = decimal.NewFromInt(0)
		marketInfo.PositionDirection = "null"
		marketInfo.MarginValue = decimal.NewFromInt(0)
	default:
		marketInfo.PositionQty, _ = decimal.NewFromString(position.Quantity)
		scale := decimal.New(1, int32(-marketInfo.QuoteDenomDecimals))
		marginCos, _ := decimal.NewFromString(position.Margin)
		marketInfo.MarginValue = marginCos.Mul(scale)
		marketInfo.PositionDirection = position.Direction
	}
	marketInfo.CalInventoryPCT(marketInfo.MarginValue)
}

func (s *tradingSvc) GetTopOfBook(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, marketInfo *DerivativeMarketInfo) error {
	book, err := s.derivativesClient.Orderbook(ctx, &derivativeExchangePB.OrderbookRequest{
		MarketId: m.MarketId,
	})
	if err != nil {
		return err
	}
	if len(book.Orderbook.Buys) > 0 {
		marketInfo.TopBidPrice = cosmtypes.MustNewDecFromStr(book.Orderbook.Buys[0].Price)
	} else {
		marketInfo.TopBidPrice = cosmtypes.NewDec(0)
	}
	if len(book.Orderbook.Sells) > 0 {
		marketInfo.TopAskPrice = cosmtypes.MustNewDecFromStr(book.Orderbook.Sells[0].Price)
	} else {
		marketInfo.TopAskPrice = cosmtypes.NewDec(0)
	}
	return nil
}
