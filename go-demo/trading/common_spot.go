package trading

import (
	"strings"
	"sync"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
	"github.com/shopspring/decimal"
)

type SpotMarketInfo struct {
	Ticker              string
	BaseDenom           string
	BaseDenomDecimals   int
	BaseSymbol          string
	QuoteDenom          string
	QuoteDenomDecimals  int
	QuoteSymbol         string
	MarketID            common.Hash
	MinPriceTickSize    cosmtypes.Dec
	MinQuantityTickSize cosmtypes.Dec
	// balance info
	BaseTotalBalance      decimal.Decimal
	QuoteTotalBalance     decimal.Decimal
	BaseAvailableBalance  decimal.Decimal
	QuoteAvailableBalance decimal.Decimal
	AccountValue          decimal.Decimal
	// risk controls
	StopStrategy          bool
	StopStrategyForDay    bool
	StopStrategyCountDown time.Time
	TimeOfNextUTCDay      time.Time
	LastSendMessageTime   []time.Time
	ReachMaxPosition      bool
	// for market making
	OraclePrice        decimal.Decimal
	CosmOraclePrice    cosmtypes.Dec
	MaxOrderSize       decimal.Decimal
	MaxOrderValue      decimal.Decimal
	HistoricalPrices   []decimal.Decimal
	HistoricalValues   []decimal.Decimal
	MaxPositionPct     decimal.Decimal
	MinPnlPct          decimal.Decimal
	MaxDDPct           decimal.Decimal
	MinPnlInitialValue decimal.Decimal
	// as model
	MinVolatilityPCT float64
	MarketVolatility decimal.Decimal
	InventoryPCT     decimal.Decimal
	FillIndensity    float64
	RiskAversion     float64
	ReservedPrice    decimal.Decimal
	OptSpread        decimal.Decimal
	// staking orders
	BestAsk        decimal.Decimal
	BestBid        decimal.Decimal
	UpperBound     decimal.Decimal
	LowerBound     decimal.Decimal
	// orders
	BidOrders OrdersBranch
	AskOrders OrdersBranch
}

type OrdersBranch struct {
	mux    sync.RWMutex // read write lock
	Orders []*spotExchangePB.SpotLimitOrder
}

func SpotMarketToMarketInfo(m *spotExchangePB.SpotMarketInfo) *SpotMarketInfo {
	var baseDenomDecimals, quoteDenomDecimals int

	if m.BaseTokenMeta != nil {
		baseDenomDecimals = int(m.BaseTokenMeta.Decimals)
	} else {
		baseDenomDecimals = 18
	}

	if m.QuoteTokenMeta != nil {
		quoteDenomDecimals = int(m.QuoteTokenMeta.Decimals)
	} else {
		quoteDenomDecimals = 6
	}

	minPriceTickSize, _ := cosmtypes.NewDecFromStr(m.MinPriceTickSize)
	minQuantityTickSize, _ := cosmtypes.NewDecFromStr(m.MinQuantityTickSize)

	tmp := strings.Split(m.Ticker, "/")

	return &SpotMarketInfo{
		Ticker:              m.Ticker, // ex INJ/USDT
		BaseDenom:           m.BaseDenom,
		BaseDenomDecimals:   baseDenomDecimals,
		QuoteDenom:          m.QuoteDenom,
		QuoteDenomDecimals:  quoteDenomDecimals,
		MarketID:            common.HexToHash(m.MarketId),
		MinPriceTickSize:    minPriceTickSize,
		MinQuantityTickSize: minQuantityTickSize,
		BaseSymbol:          tmp[0],
		QuoteSymbol:         tmp[1],
	}
}

type SpotOrderData struct {
	OrderType    exchangetypes.OrderType
	Price        cosmtypes.Dec
	Quantity     cosmtypes.Dec
	FeeRecipient string
}

func NewSpotOrder(subaccountID common.Hash, m *SpotMarketInfo, d *SpotOrderData) *exchangetypes.SpotOrder {
	return &exchangetypes.SpotOrder{
		MarketId:  m.MarketID.Hex(),
		OrderType: d.OrderType,
		OrderInfo: exchangetypes.OrderInfo{
			SubaccountId: subaccountID.Hex(),
			FeeRecipient: d.FeeRecipient,
			Price:        d.Price,
			Quantity:     d.Quantity,
		},
	}
}

// make valid qty for cefi exchange
func MakeValidQty(price, notional float64, sizePrecision int) float64 {
	limit := notional
	for {
		amount := notional / price
		Ramount := Round(amount, sizePrecision)
		if Ramount*price < limit {
			notional *= 1.05
		} else {
			return Ramount
		}
	}
}
