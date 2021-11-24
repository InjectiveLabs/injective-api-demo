package trading

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
	"github.com/shopspring/decimal"
)

const (
	Add    = "Add"
	Reduce = "Reduce"
	Wait   = "Wait"
)

func (m *DerivativeMarketInfo) SortingDerivativeLimitOrders(respOrders []*derivativeExchangePB.DerivativeLimitOrder) {
	l := len(respOrders)
	if l == 0 {
		return
	}
	var wg sync.WaitGroup
	bids := make([]*derivativeExchangePB.DerivativeLimitOrder, 0, l)
	asks := make([]*derivativeExchangePB.DerivativeLimitOrder, 0, l)
	for _, order := range respOrders {
		switch order.OrderSide {
		case "sell":
			asks = append(asks, order)
		case "buy":
			bids = append(bids, order)
		}
	}
	wg.Add(2)
	go func() {
		sort.Slice(bids, func(p, q int) bool {
			cosp, _ := cosmtypes.NewDecFromStr(bids[p].Price)
			cosq, _ := cosmtypes.NewDecFromStr(bids[q].Price)
			return cosp.GT(cosq)
		})
		wg.Done()
	}()
	go func() {
		sort.Slice(asks, func(p, q int) bool {
			cosp, _ := cosmtypes.NewDecFromStr(asks[p].Price)
			cosq, _ := cosmtypes.NewDecFromStr(asks[q].Price)
			return cosp.LT(cosq)
		})
		wg.Done()
	}()
	wg.Wait()
	m.BidOrders.mux.Lock()
	m.BidOrders.Orders = bids
	m.BidOrders.mux.Unlock()
	m.AskOrders.mux.Lock()
	m.AskOrders.Orders = asks
	m.AskOrders.mux.Unlock()
}

// check order is below / above mid price to prevent self trade
func (m *DerivativeMarketInfo) CheckNewOrderIsSafe(orderType string, newOrderPrice, bestAskPrice, bestBidPrice cosmtypes.Dec, oldBidOrder, oldAskOrder *derivativeExchangePB.DerivativeLimitOrder) (safe bool) {
	if m.CosmOraclePrice.IsZero() {
		return safe
	}
	switch strings.ToLower(orderType) {
	case "buy":
		if oldAskOrder == nil {
			if !newOrderPrice.GTE(m.CosmOraclePrice) && !newOrderPrice.Add(m.MinPriceTickSize).GTE(bestAskPrice) {
				safe = true
			}
		} else {
			oldBestPrice := cosmtypes.MustNewDecFromStr(oldAskOrder.Price)
			if !newOrderPrice.GTE(m.CosmOraclePrice) && !newOrderPrice.Add(m.MinPriceTickSize).GTE(oldBestPrice) && !newOrderPrice.Add(m.MinPriceTickSize).GTE(bestAskPrice) {
				safe = true
			}
		}
	case "sell":
		if oldBidOrder == nil {
			if !newOrderPrice.LTE(m.CosmOraclePrice) && !newOrderPrice.Sub(m.MinPriceTickSize).LTE(bestBidPrice) {
				safe = true
			}
		} else {
			oldBestPrice := cosmtypes.MustNewDecFromStr(oldBidOrder.Price)
			if !newOrderPrice.LTE(m.CosmOraclePrice) && !newOrderPrice.Sub(m.MinPriceTickSize).LTE(oldBestPrice) && !newOrderPrice.Sub(m.MinPriceTickSize).LTE(bestBidPrice) {
				safe = true
			}
		}
	}
	return safe
}

func (m *DerivativeMarketInfo) UpdateBidOrders(inputOrder *derivativeExchangePB.DerivativeLimitOrder) {
	m.BidOrders.mux.Lock()
	defer m.BidOrders.mux.Unlock()
	l := len(m.BidOrders.Orders)
	if l == 0 {
		return
	}
	for i := 0; i < l; i++ {
		hash := m.BidOrders.Orders[i].OrderHash
		if inputOrder.OrderHash == hash {
			m.BidOrders.Orders[i] = inputOrder
		}
	}
}

func (m *DerivativeMarketInfo) UpdateAskOrders(inputOrder *derivativeExchangePB.DerivativeLimitOrder) {
	m.AskOrders.mux.Lock()
	defer m.AskOrders.mux.Unlock()
	l := len(m.AskOrders.Orders)
	if l == 0 {
		return
	}
	for i := 0; i < l; i++ {
		hash := m.AskOrders.Orders[i].OrderHash
		if inputOrder.OrderHash == hash {
			m.AskOrders.Orders[i] = inputOrder
		}
	}
}

func (m *DerivativeMarketInfo) CancelBidOrdersFromOrderList(inputOrders []*derivativeExchangePB.DerivativeLimitOrder) {
	m.BidOrders.mux.Lock()
	defer m.BidOrders.mux.Unlock()
	l := len(m.BidOrders.Orders)
	if len(inputOrders) == 0 || l == 0 {
		return
	}
	bidIdx := map[string]struct{}{}
	for _, order := range inputOrders {
		bidIdx[order.OrderHash] = struct{}{}
	}
	var newBidOrders []*derivativeExchangePB.DerivativeLimitOrder
	for i := 0; i < l; i++ {
		hash := m.BidOrders.Orders[i].OrderHash
		if _, ok := bidIdx[hash]; !ok {
			newBidOrders = append(newBidOrders, m.BidOrders.Orders[i])
		}
	}
	m.BidOrders.Orders = newBidOrders
}

func (m *DerivativeMarketInfo) CancelBidOrdersFromOrderListByHash(inputHash []string) {
	m.BidOrders.mux.Lock()
	defer m.BidOrders.mux.Unlock()
	l := len(m.BidOrders.Orders)
	if len(inputHash) == 0 || l == 0 {
		return
	}
	bidIdx := map[string]struct{}{}
	for _, hash := range inputHash {
		bidIdx[hash] = struct{}{}
	}
	var newBidOrders []*derivativeExchangePB.DerivativeLimitOrder
	for i := 0; i < l; i++ {
		hash := m.BidOrders.Orders[i].OrderHash
		if _, ok := bidIdx[hash]; !ok {
			newBidOrders = append(newBidOrders, m.BidOrders.Orders[i])
		}
	}
	m.BidOrders.Orders = newBidOrders
}

func (m *DerivativeMarketInfo) CancelAskOrdersFromOrderList(inputOrders []*derivativeExchangePB.DerivativeLimitOrder) {
	m.AskOrders.mux.Lock()
	defer m.AskOrders.mux.Unlock()
	l := len(m.AskOrders.Orders)
	if len(inputOrders) == 0 || l == 0 {
		return
	}
	askIdx := map[string]struct{}{}
	for _, order := range inputOrders {
		askIdx[order.OrderHash] = struct{}{}
	}
	var newAskOrders []*derivativeExchangePB.DerivativeLimitOrder
	for i := 0; i < l; i++ {
		hash := m.AskOrders.Orders[i].OrderHash
		if _, ok := askIdx[hash]; !ok {
			newAskOrders = append(newAskOrders, m.AskOrders.Orders[i])
		}
	}
	m.AskOrders.Orders = newAskOrders
}

func (m *DerivativeMarketInfo) CancelAskOrdersFromOrderListByHash(inputHash []string) {
	m.AskOrders.mux.Lock()
	defer m.AskOrders.mux.Unlock()
	l := len(m.AskOrders.Orders)
	if len(inputHash) == 0 || l == 0 {
		return
	}
	askIdx := map[string]struct{}{}
	for _, hash := range inputHash {
		askIdx[hash] = struct{}{}
	}
	var newAskOrders []*derivativeExchangePB.DerivativeLimitOrder
	for i := 0; i < l; i++ {
		hash := m.AskOrders.Orders[i].OrderHash
		if _, ok := askIdx[hash]; !ok {
			newAskOrders = append(newAskOrders, m.AskOrders.Orders[i])
		}
	}
	m.AskOrders.Orders = newAskOrders
}

func (m *DerivativeMarketInfo) InsertBidOrders(inputOrder *derivativeExchangePB.DerivativeLimitOrder) {
	var needToSort bool = false
	m.BidOrders.mux.RLock()
	newBidOrders := m.BidOrders.Orders
	m.BidOrders.mux.RUnlock()

	if m.IsMyBidOrder(inputOrder.OrderHash) {
		// already in the pool
		return
	}
	newBidOrders = append(newBidOrders, inputOrder)
	if !needToSort {
		needToSort = true
	}
	if needToSort {
		sort.Slice(newBidOrders, func(p, q int) bool {
			cosp, _ := cosmtypes.NewDecFromStr(newBidOrders[p].Price)
			cosq, _ := cosmtypes.NewDecFromStr(newBidOrders[q].Price)
			return cosp.GT(cosq)
		})
		m.BidOrders.mux.Lock()
		m.BidOrders.Orders = newBidOrders
		m.BidOrders.mux.Unlock()
	} // else no need to re-define BidOrders
}

func (m *DerivativeMarketInfo) InsertAskOrders(inputOrder *derivativeExchangePB.DerivativeLimitOrder) {
	var needToSort bool = false
	m.AskOrders.mux.RLock()
	newAskOrders := m.AskOrders.Orders
	m.AskOrders.mux.RUnlock()

	if m.IsMyAskOrder(inputOrder.OrderHash) {
		return
	}
	newAskOrders = append(newAskOrders, inputOrder)
	if !needToSort {
		needToSort = true
	}
	if needToSort {
		sort.Slice(newAskOrders, func(p, q int) bool {
			cosp, _ := cosmtypes.NewDecFromStr(newAskOrders[p].Price)
			cosq, _ := cosmtypes.NewDecFromStr(newAskOrders[q].Price)
			return cosp.LT(cosq)
		})
		m.AskOrders.mux.Lock()
		m.AskOrders.Orders = newAskOrders
		m.AskOrders.mux.Unlock()
	}
}

func (m *DerivativeMarketInfo) GetBidOrdersLen() (l int) {
	m.BidOrders.mux.RLock()
	l = len(m.BidOrders.Orders)
	m.BidOrders.mux.RUnlock()
	return l
}

func (m *DerivativeMarketInfo) GetAskOrdersLen() (l int) {
	m.AskOrders.mux.RLock()
	l = len(m.AskOrders.Orders)
	m.AskOrders.mux.RUnlock()
	return l
}

func (m *DerivativeMarketInfo) GetBidOrder(level int) (order *derivativeExchangePB.DerivativeLimitOrder) {
	m.BidOrders.mux.RLock()
	defer m.BidOrders.mux.RUnlock()
	l := len(m.BidOrders.Orders)
	if level >= l {
		return order
	}
	order = m.BidOrders.Orders[level]
	return order
}

func (m *DerivativeMarketInfo) GetAskOrder(level int) (order *derivativeExchangePB.DerivativeLimitOrder) {
	m.AskOrders.mux.RLock()
	m.AskOrders.mux.RUnlock()
	l := len(m.AskOrders.Orders)
	if level >= l {
		return order
	}
	order = m.AskOrders.Orders[level]
	return order
}

func (m *DerivativeMarketInfo) IsMyBidOrder(hash string) bool {
	m.BidOrders.mux.RLock()
	defer m.BidOrders.mux.RUnlock()
	for _, order := range m.BidOrders.Orders {
		if order.OrderHash == hash {
			return true
		}
	}
	return false
}

func (m *DerivativeMarketInfo) IsMyAskOrder(hash string) bool {
	m.AskOrders.mux.RLock()
	defer m.AskOrders.mux.RUnlock()
	for _, order := range m.AskOrders.Orders {
		if order.OrderHash == hash {
			return true
		}
	}
	return false
}

func (s *tradingSvc) InitialOrderList(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	var respOrders *derivativeExchangePB.OrdersResponse
	respOrders, err := s.derivativesClient.Orders(ctx, &derivativeExchangePB.OrdersRequest{
		SubaccountId: subaccountID.Hex(),
		MarketId:     m.MarketId,
	})
	if err != nil || respOrders == nil {
		messageIdx := 1
		if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
			message := fmt.Sprintf("❌ Error while fetching %s spot orders: %s\n", m.Ticker, err.Error())
			s.logger.Errorln(message)
			marketInfo.LastSendMessageTime[messageIdx] = time.Now()
		}
		return
	}
	new := len(respOrders.Orders)
	// maintaining order status
	marketInfo.MaintainOrderStatus(new)
	// get sorted bid & ask order lists
	marketInfo.SortingDerivativeLimitOrders(respOrders.Orders)

}

// pull orders from exchange every few mins, to make sure we are uptodate
func (s *tradingSvc) UpdateInjectiveOrderSession(ctx context.Context, m *derivativeExchangePB.DerivativeMarketInfo, subaccountID *common.Hash, marketInfo *DerivativeMarketInfo) {
	OrderCheck := time.NewTicker(time.Second * 60)
	defer OrderCheck.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-OrderCheck.C:
			s.InitialOrderList(ctx, m, subaccountID, marketInfo)
			s.logger.Infof("Updated Injective %s spot orders\n", m.Ticker)
		default:
			time.Sleep(time.Second)
		}
	}
}

func (m *DerivativeMarketInfo) GetOrderSizeFromBidOrders(hash string) (price, size float64) {
	m.BidOrders.mux.RLock()
	defer m.BidOrders.mux.RUnlock()
	for _, order := range m.BidOrders.Orders {
		if order.OrderHash == hash {
			qty, _ := decimal.NewFromString(order.Quantity)
			floatQty, _ := qty.Float64()
			scale := decimal.New(1, int32(-m.QuoteDenomDecimals))
			unScalePrice, _ := decimal.NewFromString(order.Price)
			floatPrice, _ := unScalePrice.Mul(scale).Float64()
			return floatPrice, floatQty
		}
	}
	return 0, 0
}

func (m *DerivativeMarketInfo) GetOrderSizeFromAskOrders(hash string) (price, size float64) {
	m.AskOrders.mux.RLock()
	defer m.AskOrders.mux.RUnlock()
	for _, order := range m.AskOrders.Orders {
		if order.OrderHash == hash {
			qty, _ := decimal.NewFromString(order.Quantity)
			floatQty, _ := qty.Float64()
			scale := decimal.New(1, int32(-m.QuoteDenomDecimals))
			unScalePrice, _ := decimal.NewFromString(order.Price)
			floatPrice, _ := unScalePrice.Mul(scale).Float64()
			return floatPrice, floatQty
		}
	}
	return 0, 0
}
