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

	residue := new(big.Int).Mod(decPrice.BigInt(), minPriceTickSize.BigInt())
	//fmt.Printf("%s mod %s is %s\n",decPrice.BigInt().String(), minPriceTickSize.BigInt().String(), residue.String())
	formattedPrice := new(big.Int).Sub(decPrice.BigInt(), residue)
	//fmt.Println(residue.String(), formattedPrice.String(), cosmtypes.NewDecFromBigInt(formattedPrice).String())
	//fmt.Println(decPrice.String(), minPriceTickSize.String())
	p := decimal.NewFromBigInt(formattedPrice, -18).String()
	//fmt.Println("p", p)
	realPrice, _ := cosmtypes.NewDecFromStr(p)
	//fmt.Println("returning realPrice", realPrice.String())
	return realPrice
}

func formatToTickSize(value, tickSize cosmtypes.Dec) cosmtypes.Dec {
	residue := new(big.Int).Mod(value.BigInt(), tickSize.BigInt())
	formattedValue := new(big.Int).Sub(value.BigInt(), residue)
	p := decimal.NewFromBigInt(formattedValue, -18).String()
	realValue, _ := cosmtypes.NewDecFromStr(p)
	return realValue
}

// convert decimal.Decimal into acceptable quantity, (input value's unit is coin, ex: 5 inj)
func getQuantity(value decimal.Decimal, minTickSize cosmtypes.Dec, baseDecimals int) (qty cosmtypes.Dec) {
	mid, _ := cosmtypes.NewDecFromStr(value.String())
	bStr := decimal.New(1, int32(baseDecimals)).String()
	baseDec, _ := cosmtypes.NewDecFromStr(bStr)
	scale := baseDec.Quo(minTickSize) // from tick size to coin size
	midScaledInt := mid.Mul(scale).TruncateDec()
	qty = minTickSize.Mul(midScaledInt)
	return qty
}

//convert cosmostype.Dec into readable string price
func getPriceForPrintOut(price cosmtypes.Dec, baseDecimals, quoteDecimals int) (priceOut float64) {
	scale := decimal.New(1, int32(baseDecimals-quoteDecimals)).String()
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
