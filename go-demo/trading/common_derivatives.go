package trading

import (
	"sync"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	oracletypes "github.com/InjectiveLabs/sdk-go/chain/oracle/types"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
	"github.com/shopspring/decimal"
)

const DerivativeBookSideOrderCount = 4

type DerivativeOrderData struct {
	OrderType    exchangetypes.OrderType
	Price        cosmtypes.Dec
	Quantity     cosmtypes.Dec
	Margin       cosmtypes.Dec
	FeeRecipient string
}
type DerivativeMarketInfo struct {
	Ticker              string
	QuoteDenom          string
	QuoteDenomDecimals  int
	OracleBase          string
	OracleQuote         string
	OracleType          oracletypes.OracleType
	OracleScaleFactor   uint32
	IsPerpetual         bool
	MarketID            common.Hash
	MarkPrice           cosmtypes.Dec
	MinPriceTickSize    cosmtypes.Dec
	MinQuantityTickSize cosmtypes.Dec
	BaseSymbol          string
	QuoteSymbol         string
	// balance info
	//BaseBalances InjectiveBaseAssetsBranch
	AccountValue decimal.Decimal
	// risk controls
	PositionDirection   string
	PositionQty         decimal.Decimal
	MarginValue         decimal.Decimal
	LastSendMessageTime []time.Time
	ReachMaxPosition    bool
	// for market making
	LocalOrderBook  []interface{}
	OraclePrice     decimal.Decimal
	OracleReady     bool
	CosmOraclePrice cosmtypes.Dec
	MaxOrderSize    decimal.Decimal
	MaxOrderValue   decimal.Decimal
	TopBidPrice     cosmtypes.Dec
	TopAskPrice     cosmtypes.Dec

	OrderMain OrderMaintainBranch
	// as model
	MinVolatilityPCT float64
	MarketVolatility decimal.Decimal
	InventoryPCT     decimal.Decimal
	FillIndensity    float64
	RiskAversion     float64
	ReservedPrice    decimal.Decimal
	OptSpread        decimal.Decimal
	// staking orders
	BestAsk decimal.Decimal
	BestBid decimal.Decimal
	// orders
	BidOrders OrdersBranch
	AskOrders OrdersBranch
}

type OrderMaintainBranch struct {
	mux      sync.RWMutex
	Status   string
	Updated  bool
	LastSend time.Time
}

type CumFilledBranch struct {
	mux           sync.RWMutex
	Amount        decimal.Decimal
	LastCheckTime time.Time
}

type OrdersBranch struct {
	mux    sync.RWMutex // read write lock
	Orders []*derivativeExchangePB.DerivativeLimitOrder
}

func NewDerivativeOrder(subaccountID common.Hash, m *DerivativeMarketInfo, d *DerivativeOrderData) *exchangetypes.DerivativeOrder {

	return &exchangetypes.DerivativeOrder{
		MarketId:  m.MarketID.Hex(),
		OrderType: d.OrderType,
		OrderInfo: exchangetypes.OrderInfo{
			SubaccountId: subaccountID.Hex(),
			FeeRecipient: d.FeeRecipient,
			Price:        d.Price,
			Quantity:     d.Quantity,
		},
		Margin: d.Margin,
	}
}

func DerivativeMarketToMarketInfo(m *derivativeExchangePB.DerivativeMarketInfo) *DerivativeMarketInfo {

	var quoteDenomDecimals int

	if m.QuoteTokenMeta != nil {
		quoteDenomDecimals = int(m.QuoteTokenMeta.Decimals)
	} else {
		quoteDenomDecimals = 6
	}
	oracleType, _ := oracletypes.GetOracleType(m.OracleType)
	minPriceTickSize, _ := cosmtypes.NewDecFromStr(m.MinPriceTickSize)
	minQuantityTickSize, _ := cosmtypes.NewDecFromStr(m.MinQuantityTickSize)
	return &DerivativeMarketInfo{
		Ticker:              m.Ticker,
		QuoteDenom:          m.QuoteDenom,
		QuoteDenomDecimals:  quoteDenomDecimals,
		OracleBase:          m.OracleBase,
		OracleQuote:         m.OracleQuote,
		OracleType:          oracleType,
		OracleScaleFactor:   m.OracleScaleFactor,
		IsPerpetual:         m.IsPerpetual,
		MarketID:            common.HexToHash(m.MarketId),
		MinPriceTickSize:    minPriceTickSize,
		MinQuantityTickSize: minQuantityTickSize,
	}
}

func (m *DerivativeMarketInfo) UpdateOrderMain(status string) {
	m.OrderMain.mux.Lock()
	defer m.OrderMain.mux.Unlock()
	m.OrderMain.Status = status
	m.OrderMain.LastSend = time.Now()
	m.OrderMain.Updated = false
}

func (m *DerivativeMarketInfo) MaintainOrderStatus(new int) {
	m.OrderMain.mux.Lock()
	defer m.OrderMain.mux.Unlock()
	if time.Now().After(m.OrderMain.LastSend.Add(time.Second * 15)) {
		m.OrderMain.Updated = true
		m.OrderMain.Status = Wait
	} else {
		orignal := m.GetBidOrdersLen() + m.GetAskOrdersLen()
		switch m.OrderMain.Status {
		case Add:
			if orignal < new {
				m.OrderMain.Updated = true
			}
		case Reduce:
			if orignal > new {
				m.OrderMain.Updated = true
			}
		}
	}
}

func (m *DerivativeMarketInfo) IsOrderUpdated() bool {
	m.OrderMain.mux.RLock()
	defer m.OrderMain.mux.RUnlock()
	return m.OrderMain.Updated
}
