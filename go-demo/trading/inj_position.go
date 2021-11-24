package trading

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"time"

	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	"github.com/shopspring/decimal"
)

func (s *tradingSvc) GetInjectivePositions(ctx context.Context) error {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	resp, err := s.derivativesClient.Positions(ctx, &derivativeExchangePB.PositionsRequest{
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		s.logger.Infof("Failed to get derivative positions")
		return err
	}
	if resp == nil {
		return errors.New("get nil response from GetInjectivePositions.")
	}
	s.dataCenter.InjectivePositions.mux.Lock()
	s.dataCenter.InjectivePositions.res = resp
	s.dataCenter.InjectivePositions.mux.Unlock()
	return nil
}

func (s *tradingSvc) UpdateInjectivePositionSession(ctx context.Context, interval time.Duration) {
	var lastSend time.Time
	PositionCheck := time.NewTicker(time.Second * interval)
	defer PositionCheck.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-PositionCheck.C:
			err := s.GetInjectivePositions(ctx)
			if err != nil {
				message := fmt.Sprintf("❌ Failed to get Injective positions with err: %s, resend in 10min if still not working\n", err.Error())
				if !time.Now().After(lastSend.Add(time.Second * 600)) {
					s.logger.Errorln(message)
					continue
				}
				lastSend = time.Now()
				continue
			}
			s.logger.Infoln("Updated Injective positions data")
		default:
			time.Sleep(time.Second)
		}
	}
}

func (s *tradingSvc) IsAlreadyInPositions(ticker string) bool {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	s.dataCenter.InjectivePositions.mux.RLock()
	defer s.dataCenter.InjectivePositions.mux.RUnlock()
	for _, pos := range s.dataCenter.InjectivePositions.res.Positions {
		if pos.Ticker == ticker && pos.SubaccountId == subaccountID.Hex() {
			return true
		}
	}
	return false
}

func (s *tradingSvc) GetInjectivePositionData(ticker string) *derivativeExchangePB.DerivativePosition {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	s.dataCenter.InjectivePositions.mux.RLock()
	defer s.dataCenter.InjectivePositions.mux.RUnlock()
	for _, pos := range s.dataCenter.InjectivePositions.res.Positions {
		if pos.Ticker == ticker && pos.SubaccountId == subaccountID.Hex() {
			return pos
		}
	}
	return nil
}

func (s *tradingSvc) AddNewInjectivePosition(pos *derivativeExchangePB.DerivativePosition) {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	if pos.SubaccountId != subaccountID.Hex() {
		return
	}
	s.dataCenter.InjectivePositions.mux.Lock()
	defer s.dataCenter.InjectivePositions.mux.Unlock()
	s.dataCenter.InjectivePositions.res.Positions = append(s.dataCenter.InjectivePositions.res.Positions, pos)
}

func (s *tradingSvc) UpdateInjectivePosition(pos *derivativeExchangePB.DerivativePosition) {
	s.dataCenter.InjectivePositions.mux.Lock()
	defer s.dataCenter.InjectivePositions.mux.Unlock()
	for i, oldPos := range s.dataCenter.InjectivePositions.res.Positions {
		if oldPos.Ticker == pos.Ticker {
			s.dataCenter.InjectivePositions.res.Positions[i] = pos
		}
	}
}

func (s *tradingSvc) DeleteInjectivePosition(ticker string) {
	s.dataCenter.InjectivePositions.mux.Lock()
	defer s.dataCenter.InjectivePositions.mux.Unlock()
	for i, oldPos := range s.dataCenter.InjectivePositions.res.Positions {
		if oldPos.Ticker == ticker {
			s.dataCenter.InjectivePositions.res.Positions = append(s.dataCenter.InjectivePositions.res.Positions[:i], s.dataCenter.InjectivePositions.res.Positions[i+1:]...)
		}
	}
}

func (s *tradingSvc) IncreasePositionMargin(amount decimal.Decimal, m *derivativeExchangePB.DerivativeMarketInfo) {
	CosAmount := cosmtypes.MustNewDecFromStr(amount.String())
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	msgs := make([]cosmtypes.Msg, 0, 10)
	msg := &exchangetypes.MsgIncreasePositionMargin{
		Sender:                  sender.String(),
		MarketId:                m.MarketId,
		SourceSubaccountId:      subaccountID.Hex(),
		DestinationSubaccountId: subaccountID.Hex(),
		Amount:                  CosAmount,
	}
	msgs = append(msgs, msg)
	if _, err := s.cosmosClient.AsyncBroadcastMsg(msgs...); err != nil {
		var buffer bytes.Buffer
		buffer.WriteString("fail to increase position margin for ")
		buffer.WriteString(m.Ticker)
		buffer.WriteString(", probably not enough margin for the positions, go check it up!")
		message := buffer.String()
		s.logger.Warningln(message)
	} else {
		s.logger.Infof("Increased position margin.")
	}
}
