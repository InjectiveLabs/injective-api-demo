package trading

import (
	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	oracletypes "github.com/InjectiveLabs/sdk-go/chain/oracle/types"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
)

const DerivativeBookSideOrderCount = 19

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
