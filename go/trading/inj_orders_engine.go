package trading

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/ethereum/go-ethereum/common"
)

func (m *SpotMarketInfo) SortingSpotLimitOrders(respOrders []*spotExchangePB.SpotLimitOrder) {
	l := len(respOrders)
	if l == 0 {
		return
	}
	var wg sync.WaitGroup
	bids := make([]*spotExchangePB.SpotLimitOrder, 0, l)
	asks := make([]*spotExchangePB.SpotLimitOrder, 0, l)
	for _, order := range respOrders {
		switch order.OrderType {
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
func (m *SpotMarketInfo) CheckNewOrderIsSafe(orderType string, newOrderPrice, bestAskPrice, bestBidPrice cosmtypes.Dec, oldBidOrder, oldAskOrder *spotExchangePB.SpotLimitOrder) (safe bool) {
	if m.CosmOraclePrice.IsZero() {
		return safe
	}
	switch strings.ToLower(orderType) {
	case "buy":
		if oldAskOrder == nil {
			if !newOrderPrice.GTE(m.CosmOraclePrice) && !newOrderPrice.GTE(bestAskPrice) {
				safe = true
			}
		} else {
			oldBestPrice := cosmtypes.MustNewDecFromStr(oldAskOrder.Price)
			if !newOrderPrice.GTE(m.CosmOraclePrice) && !newOrderPrice.GTE(oldBestPrice) && !newOrderPrice.GTE(bestAskPrice) { // shall compare bid ask price as well, to do!!
				safe = true
			}
		}
	case "sell":
		if oldBidOrder == nil {
			if !newOrderPrice.LTE(m.CosmOraclePrice) && !newOrderPrice.LTE(bestBidPrice) {
				safe = true
			}
		} else {
			oldBestPrice := cosmtypes.MustNewDecFromStr(oldBidOrder.Price)
			if !newOrderPrice.LTE(m.CosmOraclePrice) && !newOrderPrice.LTE(oldBestPrice) && !newOrderPrice.LTE(bestBidPrice) {
				safe = true
			}
		}
	}
	return safe
}

func (m *SpotMarketInfo) CancelBidOrdersFromOrderList(inputOrders []*spotExchangePB.SpotLimitOrder) {
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
	var newBidOrders []*spotExchangePB.SpotLimitOrder
	for i := 0; i < l; i++ {
		hash := m.BidOrders.Orders[i].OrderHash
		if _, ok := bidIdx[hash]; !ok {
			newBidOrders = append(newBidOrders, m.BidOrders.Orders[i])
		}
	}
	m.BidOrders.Orders = newBidOrders
}

func (m *SpotMarketInfo) CancelBidOrdersFromOrderListByHash(inputHash []string) {
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
	var newBidOrders []*spotExchangePB.SpotLimitOrder
	for i := 0; i < l; i++ {
		hash := m.BidOrders.Orders[i].OrderHash
		if _, ok := bidIdx[hash]; !ok {
			newBidOrders = append(newBidOrders, m.BidOrders.Orders[i])
		}
	}
	m.BidOrders.Orders = newBidOrders
}

func (m *SpotMarketInfo) CancelAskOrdersFromOrderList(inputOrders []*spotExchangePB.SpotLimitOrder) {
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
	var newAskOrders []*spotExchangePB.SpotLimitOrder
	for i := 0; i < l; i++ {
		hash := m.AskOrders.Orders[i].OrderHash
		if _, ok := askIdx[hash]; !ok {
			newAskOrders = append(newAskOrders, m.AskOrders.Orders[i])
		}
	}
	m.AskOrders.Orders = newAskOrders
}

func (m *SpotMarketInfo) CancelAskOrdersFromOrderListByHash(inputHash []string) {
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
	var newAskOrders []*spotExchangePB.SpotLimitOrder
	for i := 0; i < l; i++ {
		hash := m.AskOrders.Orders[i].OrderHash
		if _, ok := askIdx[hash]; !ok {
			newAskOrders = append(newAskOrders, m.AskOrders.Orders[i])
		}
	}
	m.AskOrders.Orders = newAskOrders
}

func (m *SpotMarketInfo) InsertBidOrders(inputOrders []*spotExchangePB.SpotLimitOrder) {
	if len(inputOrders) == 0 {
		return
	}
	m.BidOrders.mux.Lock()
	defer m.BidOrders.mux.Unlock()
	l := len(m.BidOrders.Orders)
	if l == 0 {
		m.BidOrders.Orders = inputOrders
		return
	}
	newBidOrders := m.BidOrders.Orders
	newBidOrders = append(newBidOrders, inputOrders...)
	sort.Slice(newBidOrders, func(p, q int) bool {
		cosp, _ := cosmtypes.NewDecFromStr(newBidOrders[p].Price)
		cosq, _ := cosmtypes.NewDecFromStr(newBidOrders[q].Price)
		return cosp.GT(cosq)
	})
	m.BidOrders.Orders = newBidOrders
}

func (m *SpotMarketInfo) InsertAskOrders(inputOrders []*spotExchangePB.SpotLimitOrder) {
	if len(inputOrders) == 0 {
		return
	}
	m.AskOrders.mux.Lock()
	defer m.AskOrders.mux.Unlock()
	l := len(m.AskOrders.Orders)
	if l == 0 {
		m.AskOrders.Orders = inputOrders
		return
	}
	newAskOrders := m.AskOrders.Orders
	newAskOrders = append(newAskOrders, inputOrders...)
	sort.Slice(newAskOrders, func(p, q int) bool {
		cosp, _ := cosmtypes.NewDecFromStr(newAskOrders[p].Price)
		cosq, _ := cosmtypes.NewDecFromStr(newAskOrders[q].Price)
		return cosp.LT(cosq)
	})
	m.AskOrders.Orders = newAskOrders
}

func (m *SpotMarketInfo) GetBidOrdersLen() (l int) {
	m.BidOrders.mux.RLock()
	l = len(m.BidOrders.Orders)
	m.BidOrders.mux.RUnlock()
	return l
}

func (m *SpotMarketInfo) GetAskOrdersLen() (l int) {
	m.AskOrders.mux.RLock()
	l = len(m.AskOrders.Orders)
	m.AskOrders.mux.RUnlock()
	return l
}

func (m *SpotMarketInfo) GetNewBidOrdersFromReduce(s *tradingSvc) (canceledOrders []*spotExchangePB.SpotLimitOrder) {
	m.BidOrders.mux.Lock()
	defer m.BidOrders.mux.Unlock()
	bidLen := len(m.BidOrders.Orders)
	extra := bidLen - s.spotSideCount
	canceledOrders = m.BidOrders.Orders[bidLen-extra:]
	newBidOrders := m.BidOrders.Orders[:s.spotSideCount]
	m.BidOrders.Orders = newBidOrders
	return canceledOrders
}

func (m *SpotMarketInfo) GetNewAskOrdersFromReduce(s *tradingSvc) (canceledOrders []*spotExchangePB.SpotLimitOrder) {
	m.AskOrders.mux.Lock()
	defer m.AskOrders.mux.Unlock()
	askLen := len(m.AskOrders.Orders)
	extra := askLen - s.spotSideCount
	canceledOrders = m.AskOrders.Orders[askLen-extra:]
	newAskOrders := m.AskOrders.Orders[:s.spotSideCount]
	m.AskOrders.Orders = newAskOrders
	return canceledOrders
}

func (m *SpotMarketInfo) GetBidOrder(level int) (order *spotExchangePB.SpotLimitOrder) {
	m.BidOrders.mux.RLock()
	defer m.BidOrders.mux.RUnlock()
	l := len(m.BidOrders.Orders)
	if level >= l {
		return order
	}
	order = m.BidOrders.Orders[level]
	return order
}

func (m *SpotMarketInfo) GetAskOrder(level int) (order *spotExchangePB.SpotLimitOrder) {
	m.AskOrders.mux.RLock()
	m.AskOrders.mux.RUnlock()
	l := len(m.AskOrders.Orders)
	if level >= l {
		return order
	}
	order = m.AskOrders.Orders[level]
	return order
}

func (m *SpotMarketInfo) IsMyBidOrder(hash string) bool {
	m.BidOrders.mux.RLock()
	defer m.BidOrders.mux.RUnlock()
	for _, order := range m.BidOrders.Orders {
		if order.OrderHash == hash {
			return true
		}
	}
	return false
}

func (m *SpotMarketInfo) IsMyAskOrder(hash string) bool {
	m.AskOrders.mux.RLock()
	defer m.AskOrders.mux.RUnlock()
	for _, order := range m.AskOrders.Orders {
		if order.OrderHash == hash {
			return true
		}
	}
	return false
}

func (s *tradingSvc) InitialOrderList(ctx context.Context, m *spotExchangePB.SpotMarketInfo, subaccountID *common.Hash, marketInfo *SpotMarketInfo, ErrCh *chan map[string]interface{}) {
	var respOrders *spotExchangePB.OrdersResponse
	respOrders, err := s.spotsClient.Orders(ctx, &spotExchangePB.OrdersRequest{
		SubaccountId: subaccountID.Hex(),
		MarketId:     m.MarketId,
	})
	if err != nil || respOrders == nil {
		messageIdx := 1
		message := fmt.Sprintf("❌ Error while fetching %s spot orders: %s\n", m.Ticker, err.Error())
		e := make(map[string]interface{})
		e["critical"] = true
		e["count"] = true
		e["wait"] = 20
		e["message"] = message
		(*ErrCh) <- e
		if time.Now().After(marketInfo.LastSendMessageTime[messageIdx].Add(time.Second * 600)) {
			go s.SendCritialAlertToDiscord(message)
			marketInfo.LastSendMessageTime[messageIdx] = time.Now()
		}
		return
	}
	// get sorted bid & ask order lists
	marketInfo.SortingSpotLimitOrders(respOrders.Orders)
}
