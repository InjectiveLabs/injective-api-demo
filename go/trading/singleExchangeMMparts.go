package trading

import (
	"bytes"
	"fmt"
	"strconv"
	"strings"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
)

// check the balance before placing order
func (s *tradingSvc) getCorrectOrderSize(m *DerivativeMarketInfo, method string, qty decimal.Decimal) (formatedQty cosmtypes.Dec, enough bool) {
	formatedQty = cosmtypes.NewDec(0)
	enough = true
	if enough {
		formatedQty = getQuantityForDerivative(qty, m.MinQuantityTickSize, m.QuoteDenomDecimals)
	}
	return formatedQty, enough
}

func (s *tradingSvc) HandleRequestMsgs(
	method string,
	allRequests int,
	Msgs interface{},
	marketInfo *DerivativeMarketInfo,
) {
	if allRequests == 0 {
		return
	}
	var batch bool = true
	switch method {
	case "cancel":
		msgs := Msgs.(*exchangetypes.MsgBatchCancelDerivativeOrders)
		CosMsgs := []cosmtypes.Msg{msgs}
		for {
			if allRequests == 0 {
				return
			}
			if res, err := s.cosmosClient.AsyncBroadcastMsg(CosMsgs...); err != nil {
				if strings.Contains(err.Error(), "order doesnt exist") {
					if batch {
						cancelMsgs := make([]cosmtypes.Msg, 0, 10)
						for _, item := range msgs.Data {
							msg := &exchangetypes.MsgCancelDerivativeOrder{
								Sender:       msgs.Sender,
								MarketId:     item.MarketId,
								SubaccountId: item.SubaccountId,
								OrderHash:    item.OrderHash,
							}
							cancelMsgs = append(cancelMsgs, msg)
						}
						CosMsgs = cancelMsgs
						allRequests = len(CosMsgs)
						batch = false
					} else {
						tmp := strings.Split(err.Error(), ":")
						idxStr := strings.Replace(tmp[3], " ", "", -1)
						idx, err := strconv.Atoi(idxStr)
						if err != nil {
							// handle
						}
						// remove error msg from msg list
						// debugging
						fmt.Println(CosMsgs[idx])
						CosMsgs = append(CosMsgs[:idx], CosMsgs[idx+1:]...)
						allRequests = len(CosMsgs)
					}
					continue
				}
				messageIdx := 2
				if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
					var buffer bytes.Buffer
					buffer.WriteString(marketInfo.Ticker)
					buffer.WriteString(" derivative market: ")
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
					s.logger.Errorln(message)
					marketInfo.LastSendMessageTime[messageIdx] = time.Now()
				}
			} else {
				if allRequests != 0 {
					var buffer bytes.Buffer
					buffer.WriteString(marketInfo.Ticker)
					buffer.WriteString(" : ")
					message := fmt.Sprintf("🗑 canceled %v ", allRequests)
					buffer.WriteString(message)
					if batch {
						buffer.WriteString("orders with batch")
					} else {
						buffer.WriteString("orders")
					}
					s.logger.Infoln(buffer.String())
					// update order status
					marketInfo.UpdateOrderMain(Reduce)
				}
				return
			}
		}
	case "post":
		msgs := Msgs.(*exchangetypes.MsgBatchCreateDerivativeLimitOrders)
		CosMsgs := []cosmtypes.Msg{msgs}
		if res, err := s.cosmosClient.AsyncBroadcastMsg(CosMsgs...); err != nil {
			messageIdx := 2
			if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
				var buffer bytes.Buffer
				buffer.WriteString(marketInfo.Ticker)
				buffer.WriteString(" derivative market: ")
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
				s.logger.Errorln(message)
				marketInfo.LastSendMessageTime[messageIdx] = time.Now()
			}
		} else {
			if allRequests != 0 {
				var buffer bytes.Buffer
				buffer.WriteString(marketInfo.Ticker)
				buffer.WriteString(" : ")
				message := fmt.Sprintf("🔥 posted %v ", allRequests)
				buffer.WriteString(message)
				buffer.WriteString("orders with batch")
				s.logger.Infoln(buffer.String())
				// update order status
				marketInfo.UpdateOrderMain(Add)
			}
		}
	case "cut":
		msgs := Msgs.(*exchangetypes.MsgCreateDerivativeMarketOrder)
		CosMsgs := []cosmtypes.Msg{msgs}
		if res, err := s.cosmosClient.AsyncBroadcastMsg(CosMsgs...); err != nil {
			messageIdx := 2
			if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
				var buffer bytes.Buffer
				buffer.WriteString(marketInfo.Ticker)
				buffer.WriteString(" derivative market: ")
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
				s.logger.Errorln(message)
				marketInfo.LastSendMessageTime[messageIdx] = time.Now()
			}
		} else {
			if allRequests != 0 {
				var buffer bytes.Buffer
				buffer.WriteString(marketInfo.Ticker)
				buffer.WriteString(" : ")
				message := fmt.Sprintf("🔥 cutted %v ", allRequests)
				buffer.WriteString(message)
				buffer.WriteString("orders with batch")
				s.logger.Infoln(buffer.String())
				// update order status
				marketInfo.UpdateOrderMain(Reduce)
			}
		}
	}
}
