package trading

import (
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/shopspring/decimal"
)

func (m *SpotMarketInfo) GetOraclePrice(single *SingleExchangeMM, historySec int) error {
	var ask, bid decimal.Decimal
	for i, exch := range single.Exchanges {
		if exch == "Binance" {
			ask, _ = single.GetAskDatas(i, 0)
			bid, _ = single.GetBidDatas(i, 0)
		}
	}
	if ask.IsZero() || bid.IsZero() {
		return errors.New("not ready yet")
	}
	m.OraclePrice = ask.Add(bid).Div(decimal.NewFromInt(2))
	m.CosmOraclePrice = getPrice(m.OraclePrice, m.BaseDenomDecimals, m.QuoteDenomDecimals, m.MinPriceTickSize)
	m.HistoricalPrices = append(m.HistoricalPrices, m.OraclePrice)
	if len(m.HistoricalPrices) > historySec {
		m.HistoricalPrices = m.HistoricalPrices[len(m.HistoricalPrices)-historySec:]
	}
	return nil
}

func (m *SpotMarketInfo) ReservationPriceAndSpread(scale decimal.Decimal) {
	//r(s,t) = s - q * gamma * sigma**2 * (T-t)
	//spread[t] = gamma * (sigma **2) + (2/gamma) * math.log(1 + (gamma/k))
	defaultPCT := 0.02
	windowPCT := decimal.NewFromFloat(defaultPCT).Mul(scale)
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

	// the moving window for ladder orders
	halfspread := m.OptSpread.Div(decimal.NewFromFloat(2))
	m.BestAsk = m.ReservedPrice.Add(halfspread)
	m.BestBid = m.ReservedPrice.Sub(halfspread)

	up := decimal.NewFromInt(1).Add(windowPCT)
	down := decimal.NewFromInt(1).Sub(windowPCT)
	m.UpperBound = m.BestAsk.Mul(up)   // 2% higher
	m.LowerBound = m.BestBid.Mul(down) // 2% lower
}

func (m *SpotMarketInfo) CalVolatility(scale decimal.Decimal) {
	minVol := m.OraclePrice.Mul(decimal.NewFromFloat(m.MinVolatilityPCT)) // set min volatility for mm strategy for now

	if len(m.HistoricalPrices) < 2 {
		m.MarketVolatility = minVol.Mul(scale)
		return
	}
	square := decimal.NewFromFloat(0.)
	average := decimal.NewFromFloat(0.)
	n := decimal.NewFromInt(int64(len(m.HistoricalPrices)))
	for _, data := range m.HistoricalPrices {
		square.Add(data.Mul(data))
		average.Add(data)
	}
	average = average.Div(n)
	square = square.Sub(average.Mul(average).Mul(n))
	square = square.Div(n.Sub(decimal.NewFromInt(1)))
	volatility := square.Pow(decimal.NewFromFloat(0.5))

	if volatility.LessThan(minVol) {
		volatility = minVol
	}
	m.MarketVolatility = volatility.Mul(scale)
}

func (m *SpotMarketInfo) CalInventoryPCT() {
	targetPCT := 0.5 // 50% of the value is base coin
	targetSize := m.AccountValue.Mul(decimal.NewFromFloat(targetPCT))
	nowSize := m.AccountValue.Sub(m.QuoteTotalBalance)
	differ := nowSize.Sub(targetSize)       // difference between now and target
	m.InventoryPCT = differ.Div(targetSize) // can be negative
}

func (s *tradingSvc) CalculateOverallvalue(m *SpotMarketInfo, historySec int, ErrCh *chan map[string]interface{}) {
	// inj max position part
	injBaseValue := m.OraclePrice.Mul(m.BaseTotalBalance)
	m.AccountValue = injBaseValue.Add(m.QuoteTotalBalance)
	if injBaseValue.GreaterThan(m.AccountValue.Mul(m.MaxPositionPct)) {
		m.ReachMaxPosition = true
		messageIdx := 3
		message := fmt.Sprintf("MAX_POSITION: Inj's %s spot account reached, only sell order will be placed.\n", m.Ticker)
		e := make(map[string]interface{})
		e["critical"] = true
		e["count"] = false
		e["wait"] = 0
		e["message"] = message
		(*ErrCh) <- e
		if time.Now().After(m.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
			go s.SendCritialAlertToDiscord(message)
			m.LastSendMessageTime[messageIdx] = time.Now()
		}
	} else {
		m.ReachMaxPosition = false
	}
	m.HistoricalValues = append(m.HistoricalValues, m.QuoteTotalBalance)
	if len(m.HistoricalValues) > historySec {
		m.HistoricalValues = m.HistoricalValues[len(m.HistoricalValues)-historySec:]
	}
}

func (m *SpotMarketInfo) IsMaxDrawDownOccur() bool {
	Max := m.HistoricalValues[0]
	min := m.HistoricalValues[0]
	for _, value := range m.HistoricalValues {
		switch {
		case value.GreaterThan(Max):
			Max = value
		case value.LessThan(min):
			min = value
		}
	}
	if min.LessThan(Max.Mul(m.MaxDDPct)) {
		return true
	}
	return false
}

func (m *SpotMarketInfo) IsMinPnlOccur() bool {
	limitValue := m.MinPnlInitialValue.Mul(decimal.NewFromInt(1).Sub(m.MinPnlPct))
	if m.QuoteTotalBalance.LessThan(limitValue) {
		return true
	}
	return false
}
