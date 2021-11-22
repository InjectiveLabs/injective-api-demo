package trading

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	accountsPB "github.com/InjectiveLabs/sdk-go/exchange/accounts_rpc/pb"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"

	"github.com/shopspring/decimal"
)

func (s *tradingSvc) UpdateInjectiveSpotAccountSession(ctx context.Context, interval time.Duration) {
	AccountCheck := time.NewTicker(time.Second * interval)
	defer AccountCheck.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-AccountCheck.C:
			err := s.GetInjectiveSpotAccount(ctx)
			if err != nil {
				message := fmt.Sprintf("❌ Failed to get Injective account with err: %s, resend in 10min if still not working\n", err.Error())
				s.logger.Errorln(message)
				continue
				continue
			}
			s.UpdateInjectiveAccountBalances()
			// recording usdt values
			totalUSDT := s.GetInjectiveTotalQuoteBalance("USDT")
			overallValue := totalUSDT
			s.logger.Infof("MM strategy has %s USDT in total.", overallValue.Round(2).String())
		default:
			time.Sleep(time.Second)
		}
	}
}

func (s *tradingSvc) GetInjectiveSpotAccount(ctx context.Context) error {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	resp, err := s.accountsClient.SubaccountBalancesList(ctx, &accountsPB.SubaccountBalancesListRequest{
		SubaccountId: subaccountID.Hex(),
	})
	if err != nil {
		return err
	}
	if resp == nil {
		return errors.New("get nil response from GetInjectiveSpotAccount.")
	}
	s.dataCenter.InjectiveSpotAccount.mux.Lock()
	s.dataCenter.InjectiveSpotAccount.res = resp
	s.dataCenter.InjectiveSpotAccount.mux.Unlock()
	return nil
}

func (s *tradingSvc) InitialInjAssetWithDenom(quotes []string, resp *spotExchangePB.MarketsResponse) {
	// get asset denom from resp for easier mananging
	for _, quote := range quotes {
		for _, market := range resp.Markets {
			asset := strings.Split(market.Ticker, "/")[1]
			if quote == asset {
				if !s.IsAssetAlreadyInSliceOfInjSpotAccount(asset) {
					s.dataCenter.InjectiveSpotAccount.Assets = append(s.dataCenter.InjectiveSpotAccount.Assets, asset)
					s.dataCenter.InjectiveSpotAccount.Denoms = append(s.dataCenter.InjectiveSpotAccount.Denoms, market.QuoteDenom)
				}
				break
			}
		}
	}
	l := len(s.dataCenter.InjectiveSpotAccount.Assets)
	s.dataCenter.InjectiveSpotAccount.AvailableAmounts = make([]decimal.Decimal, l)
	s.dataCenter.InjectiveSpotAccount.TotalAmounts = make([]decimal.Decimal, l)
	s.dataCenter.InjectiveSpotAccount.LockedValues = make([]decimal.Decimal, l)
	s.dataCenter.InjectiveSpotAccount.TotalValues = make([]decimal.Decimal, l)
}

func (s *tradingSvc) IsAssetAlreadyInSliceOfInjSpotAccount(asset string) bool {
	for _, data := range s.dataCenter.InjectiveSpotAccount.Assets {
		if data == asset {
			return true
		}
	}
	return false
}

func (s *tradingSvc) InitialInjectiveAccountBalances(assets []string, resp *spotExchangePB.MarketsResponse) {
	// get quote denom from resp
	for _, asset := range assets {
		for _, market := range resp.Markets {
			tmp := strings.Split(market.Ticker, "/")
			if len(tmp) != 2 {
				continue
			}
			quoteAsset := tmp[1]
			if asset == quoteAsset {
				var quoteDenomDecimals int
				if market.QuoteTokenMeta != nil {
					quoteDenomDecimals = int(market.QuoteTokenMeta.Decimals)
				} else {
					quoteDenomDecimals = 6
				}
				data := InjectiveQuoteAssetsBranch{
					Asset:              asset,
					Denom:              market.QuoteDenom,
					QuoteDenomDecimals: quoteDenomDecimals,
				}
				s.dataCenter.InjectiveQuoteAssets = append(s.dataCenter.InjectiveQuoteAssets, data)
				break
			}
		}
	}
	s.dataCenter.InjectiveQuoteLen = len(s.dataCenter.InjectiveQuoteAssets)
	// update balances data
	s.UpdateInjectiveAccountBalances()
}

func (s *tradingSvc) UpdateInjectiveAccountBalances() {
	for i := 0; i < s.dataCenter.InjectiveQuoteLen; i++ {
		for _, item := range s.dataCenter.InjectiveSpotAccount.res.Balances {
			if s.dataCenter.InjectiveQuoteAssets[i].Denom == item.Denom {
				s.dataCenter.InjectiveQuoteAssets[i].mux.Lock()
				avaiB, _ := decimal.NewFromString(item.Deposit.AvailableBalance)
				s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance = decimal.NewFromBigInt(avaiB.BigInt(), int32(-s.dataCenter.InjectiveQuoteAssets[i].QuoteDenomDecimals))
				totalB, _ := decimal.NewFromString(item.Deposit.TotalBalance)
				s.dataCenter.InjectiveQuoteAssets[i].TotalBalance = decimal.NewFromBigInt(totalB.BigInt(), int32(-s.dataCenter.InjectiveQuoteAssets[i].QuoteDenomDecimals))
				s.dataCenter.InjectiveQuoteAssets[i].mux.Unlock()
				for j, denom := range s.dataCenter.InjectiveSpotAccount.Denoms {
					if denom == s.dataCenter.InjectiveQuoteAssets[i].Denom {
						s.dataCenter.InjectiveSpotAccount.AvailableAmounts[j] = s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance
						s.dataCenter.InjectiveSpotAccount.TotalAmounts[j] = s.dataCenter.InjectiveQuoteAssets[i].TotalBalance
						s.dataCenter.InjectiveSpotAccount.LockedValues[j] = s.dataCenter.InjectiveQuoteAssets[i].TotalBalance.Sub(s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance)
						s.dataCenter.InjectiveSpotAccount.TotalValues[j] = s.dataCenter.InjectiveSpotAccount.TotalAmounts[j]
						break
					}
				}
			}
		}
	}
}

// input asset name to get shared quote asset balance amount
func (s *tradingSvc) GetInjectiveAvailableQuoteBalance(asset string) (available decimal.Decimal) {
	for i := 0; i < s.dataCenter.InjectiveQuoteLen; i++ {
		if s.dataCenter.InjectiveQuoteAssets[i].Asset == asset {
			s.dataCenter.InjectiveQuoteAssets[i].mux.RLock()
			available = s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance
			s.dataCenter.InjectiveQuoteAssets[i].mux.RUnlock()
		}
	}
	return available
}

// input asset name to get shared quote asset total balance amount
func (s *tradingSvc) GetInjectiveTotalQuoteBalance(asset string) (total decimal.Decimal) {
	for i := 0; i < s.dataCenter.InjectiveQuoteLen; i++ {
		if s.dataCenter.InjectiveQuoteAssets[i].Asset == asset {
			s.dataCenter.InjectiveQuoteAssets[i].mux.RLock()
			total = s.dataCenter.InjectiveQuoteAssets[i].TotalBalance
			s.dataCenter.InjectiveQuoteAssets[i].mux.RUnlock()
		}
	}
	return total
}

// add asset amount to shared quote asset balance
func (s *tradingSvc) AddInjectiveAvailableQuoteBalance(asset string, amount decimal.Decimal) {
	for i := 0; i < s.dataCenter.InjectiveQuoteLen; i++ {
		if s.dataCenter.InjectiveQuoteAssets[i].Asset == asset {
			s.dataCenter.InjectiveQuoteAssets[i].mux.Lock()
			s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance = s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance.Add(amount)
			s.dataCenter.InjectiveQuoteAssets[i].mux.Unlock()
		}
	}
}

// sub asset amount to shared quote asset balance
func (s *tradingSvc) SubInjectiveAvailableQuoteBalance(asset string, amount decimal.Decimal) {
	for i := 0; i < s.dataCenter.InjectiveQuoteLen; i++ {
		if s.dataCenter.InjectiveQuoteAssets[i].Asset == asset {
			s.dataCenter.InjectiveQuoteAssets[i].mux.Lock()
			s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance = s.dataCenter.InjectiveQuoteAssets[i].AvailableBalance.Sub(amount)
			s.dataCenter.InjectiveQuoteAssets[i].mux.Unlock()
		}
	}
}
