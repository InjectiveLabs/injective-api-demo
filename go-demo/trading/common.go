package trading

import (
	"fmt"
	"math/big"
	"strconv"
	"time"

	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
	"github.com/shopspring/decimal"
)

func defaultSubaccount(acc cosmtypes.AccAddress) common.Hash {
	return common.BytesToHash(common.RightPadBytes(acc.Bytes(), 32))
}

func convertDecimalIntoCosmDec(number decimal.Decimal) cosmtypes.Dec {
	stringNumber := number.String()
	cosmDecNumber := cosmtypes.MustNewDecFromStr(stringNumber)

	return cosmDecNumber
}

func convertCosmDecIntoDecimal(number cosmtypes.Dec) decimal.Decimal {
	stringNumber := number.String()
	decimalNumber, _ := decimal.NewFromString(stringNumber)

	return decimalNumber
}

// price * 10^quoteDecimals/10^baseDecimals = price * 10^(quoteDecimals - baseDecimals)
// for INJ/USDT, INJ is the base which has 18 decimals and USDT is the quote which has 6 decimals
func getPrice(price decimal.Decimal, baseDecimals, quoteDecimals int, minPriceTickSize cosmtypes.Dec) cosmtypes.Dec {
	scale := decimal.New(1, int32(quoteDecimals-baseDecimals))
	priceStr := scale.Mul(price).StringFixed(18)
	decPrice, err := cosmtypes.NewDecFromStr(priceStr)
	if err != nil {
		fmt.Println(err.Error())
		fmt.Println(priceStr, scale.String(), price.String())
		fmt.Println(decPrice.String())
	}
	realPrice := formatToTickSize(decPrice, minPriceTickSize)
	return realPrice
}

func getPriceForDerivative(price decimal.Decimal, quoteDecimals int, minPriceTickSize cosmtypes.Dec) cosmtypes.Dec {
	decScale := decimal.New(1, int32(quoteDecimals))
	priceStr := price.Mul(decScale).StringFixed(18)
	mid := cosmtypes.MustNewDecFromStr(priceStr)
	baseDec := cosmtypes.MustNewDecFromStr("1")
	scale := baseDec.Quo(minPriceTickSize) // from tick size to coin size
	midScaledInt := mid.Mul(scale).TruncateDec()
	realPrice := minPriceTickSize.Mul(midScaledInt)
	return realPrice
}

func formatToTickSize(value, tickSize cosmtypes.Dec) cosmtypes.Dec {
	residue := new(big.Int).Mod(value.BigInt(), tickSize.BigInt())
	formattedValue := new(big.Int).Sub(value.BigInt(), residue)
	p := decimal.NewFromBigInt(formattedValue, -18).StringFixed(18)
	realValue, _ := cosmtypes.NewDecFromStr(p)
	return realValue
}

// convert decimal.Decimal into acceptable quantity, (input value's unit is coin, ex: 5 inj)
func getQuantity(value decimal.Decimal, minTickSize cosmtypes.Dec, baseDecimals int) (qty cosmtypes.Dec) {
	mid, _ := cosmtypes.NewDecFromStr(value.String())
	bStr := decimal.New(1, int32(baseDecimals)).StringFixed(18)
	baseDec, _ := cosmtypes.NewDecFromStr(bStr)
	scale := baseDec.Quo(minTickSize) // from tick size to coin size
	midScaledInt := mid.Mul(scale).TruncateDec()
	qty = minTickSize.Mul(midScaledInt)
	return qty
}

// convert decimal.Decimal into acceptable quantity, (input value's unit is coin, ex: 5 inj)
func getQuantityForDerivative(value decimal.Decimal, minTickSize cosmtypes.Dec, quoteDecimals int) (qty cosmtypes.Dec) {
	mid, _ := cosmtypes.NewDecFromStr(value.String())
	baseDec := cosmtypes.MustNewDecFromStr("1")
	scale := baseDec.Quo(minTickSize) // from tick size to coin size
	midScaledInt := mid.Mul(scale).TruncateDec()
	qty = minTickSize.Mul(midScaledInt)
	return qty
}

//convert cosmostype.Dec into readable string price
func getPriceForPrintOut(price cosmtypes.Dec, baseDecimals, quoteDecimals int) (priceOut float64) {
	scale := decimal.New(1, int32(baseDecimals-quoteDecimals)).StringFixed(18)
	scaleCos, _ := cosmtypes.NewDecFromStr(scale)
	priceStr := price.Mul(scaleCos).String()
	priceOut, _ = strconv.ParseFloat(priceStr, 64)
	return priceOut
}

//convert cosmostype.Dec into readable string price
func getPriceForPrintOutForDerivative(price cosmtypes.Dec, quoteDecimals int) (priceOut float64) {
	scale := decimal.New(1, int32(-quoteDecimals)).StringFixed(18)
	scaleCos, _ := cosmtypes.NewDecFromStr(scale)
	priceStr := price.Mul(scaleCos).String()
	priceOut, _ = strconv.ParseFloat(priceStr, 64)
	return priceOut
}

func formatQuantityToTickSize(value, minTickSize cosmtypes.Dec) cosmtypes.Dec {
	modi := value.Quo(minTickSize).TruncateDec()
	qty := modi.Mul(minTickSize)
	return qty
}

// round function for float64
func Round(v float64, decimals int) float64 {
	place := int32(decimals)
	x, _ := decimal.NewFromFloat(v).Round(place).Float64()
	return x
}

func TimeOfNextUTCDay() time.Time {
	now := time.Now().UTC()
	nextUTCday := now.Add(time.Hour * 24)
	nextUTCday = time.Date(nextUTCday.Year(), nextUTCday.Month(), nextUTCday.Day(), 0, 0, 0, 0, nextUTCday.Location())
	return nextUTCday
}

//convert cosmostype.Dec into readable decimal price
func getPriceIntoDecimalForDerivative(price cosmtypes.Dec, quoteDecimals int) (priceOut decimal.Decimal) {
	scale := decimal.New(1, int32(-quoteDecimals)).String()
	scaleCos, _ := cosmtypes.NewDecFromStr(scale)
	priceStr := price.Mul(scaleCos).String()
	priceOut, _ = decimal.NewFromString(priceStr)
	return priceOut
}