package trading

import (
	"context"
	"fmt"
	"os"
	"runtime/debug"
	"sync"
	"time"

	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	"github.com/nickname32/discordhook"
	"github.com/pkg/errors"
	log "github.com/xlab/suplog"

	chainclient "github.com/InjectiveLabs/sdk-go/chain/client"
	chaintypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	exchangetypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	accountsPB "github.com/InjectiveLabs/sdk-go/exchange/accounts_rpc/pb"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	exchangePB "github.com/InjectiveLabs/sdk-go/exchange/exchange_rpc/pb"
	oraclePB "github.com/InjectiveLabs/sdk-go/exchange/oracle_rpc/pb"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"

	"github.com/InjectiveLabs/injective-trading-bot/metrics"
)

const (
	Reverse = "reverse"
	Same    = "same"
)

// sync other exchanges' market data
type dataCenter struct {
	UpdateInterval time.Duration
}

type Service interface {
	Start() error
	Close()
}

type tradingSvc struct {
	cosmosClient        chainclient.CosmosClient
	exchangeQueryClient chaintypes.QueryClient
	bankQueryClient     banktypes.QueryClient

	accountsClient    accountsPB.InjectiveAccountsRPCClient
	exchangeClient    exchangePB.InjectiveExchangeRPCClient
	spotsClient       spotExchangePB.InjectiveSpotExchangeRPCClient
	derivativesClient derivativeExchangePB.InjectiveDerivativeExchangeRPCClient
	oracleClient      oraclePB.InjectiveOracleRPCClient

	logger  log.Logger
	svcTags metrics.Tags

	Cancel *context.CancelFunc

	// by trading-team
	appDown    bool
	sendAlert  bool
	historySec int
	injSymbols []string

	sendSelfOrder  bool
	bufferTicks    int
	minPnlPct      int
	maxDDPct       int
	maxPositionPct int

	dataCenter dataCenter
	critical   errRecord

	maxOrderValue int
	spotSideCount int
}

type errRecord struct {
	mu    sync.RWMutex
	Errs  []string
	Times []time.Time
}

func NewService(
	cosmosClient chainclient.CosmosClient,
	exchangeQueryClient chaintypes.QueryClient,
	bankQueryClient banktypes.QueryClient,
	accountsClient accountsPB.InjectiveAccountsRPCClient,
	exchangeClient exchangePB.InjectiveExchangeRPCClient,
	spotsClient spotExchangePB.InjectiveSpotExchangeRPCClient,
	derivativesClient derivativeExchangePB.InjectiveDerivativeExchangeRPCClient,
	oracleClient oraclePB.InjectiveOracleRPCClient,
	sendAlert bool,
	historySec int,
	injSymbols []string,
	sendSelfOrder bool,
	bufferTicks int,
	minPnlPct int,
	maxDDPct int,
	maxPositionPct int,
	maxOrderValue int,
	spotSideCount int,
) Service {
	// set log time stamp formatter
	formatter := &log.TextFormatter{
		FullTimestamp:   true,
		TimestampFormat: "2006-01-02 15:04:05.000",
	}
	log.DefaultLogger.SetFormatter(formatter)

	return &tradingSvc{
		logger: log.WithField("svc", "trading"),
		svcTags: metrics.Tags{
			"svc": "trading_bot",
		},

		cosmosClient:        cosmosClient,
		exchangeQueryClient: exchangeQueryClient,
		bankQueryClient:     bankQueryClient,
		accountsClient:      accountsClient,
		exchangeClient:      exchangeClient,
		spotsClient:         spotsClient,
		derivativesClient:   derivativesClient,
		oracleClient:        oracleClient,
		sendAlert:           sendAlert,
		historySec:          historySec,
		injSymbols:          injSymbols,
		sendSelfOrder:       sendSelfOrder,
		bufferTicks:         bufferTicks,
		minPnlPct:           minPnlPct,
		maxDDPct:            maxDDPct,
		maxPositionPct:      maxPositionPct,
		maxOrderValue:       maxOrderValue,
		spotSideCount:       spotSideCount,
	}
}

func (s *tradingSvc) DepositAllBankBalances(ctx context.Context) {
	sender := s.cosmosClient.FromAddress()
	resp, err := s.bankQueryClient.AllBalances(ctx, &banktypes.QueryAllBalancesRequest{
		Address:    sender.String(),
		Pagination: nil,
	})

	if err != nil {
		panic("Need bank balances")
	}
	msgs := make([]cosmtypes.Msg, 0)
	subaccountID := defaultSubaccount(sender)

	s.logger.Infoln("Preparing Injective Chain funds for deposit into exchange subaccount.")

	for _, balance := range resp.Balances {
		if balance.IsZero() {
			continue
		}

		// never let INJ balance go under 100
		if balance.Denom == "inj" {
			minINJAmount, _ := cosmtypes.NewIntFromString("200000000000000000000")
			if balance.Amount.LT(minINJAmount) {
				continue
			} else {
				balance.Amount = balance.Amount.Sub(minINJAmount)
			}
		}

		s.logger.Infof("%s:\t%s \t %s\n", balance.Denom, balance.Amount.String(), subaccountID.Hex())
		msg := exchangetypes.MsgDeposit{
			Sender:       sender.String(),
			SubaccountId: subaccountID.Hex(),
			Amount:       balance,
		}
		msgs = append(msgs, &msg)
	}
	if len(msgs) > 0 {
		if _, err := s.cosmosClient.SyncBroadcastMsg(msgs...); err != nil {
			s.logger.Errorf("Failed depositing to exchange with error %s", err.Error())
		}
	}
}

func (s *tradingSvc) MarketMakeSpotMarkets(ctx context.Context) {
	s.dataCenter.UpdateInterval = 1 // 1 sec
	// setting strategy
	strategy := "singleExchangeMM"

	accountCheckInterval := time.Duration(20)
	// setting symbol for each exchange

	resp, err := s.spotsClient.Markets(ctx, &spotExchangePB.MarketsRequest{})
	if err != nil || resp == nil {
		s.logger.Infof("Failed to get spot markets")
		return
	}

	s.appDown = false
	var strategyCount int = 0
	for _, market := range resp.Markets {
		for i, symbol := range s.injSymbols {
			if symbol == market.Ticker {
				s.StrategyHub(ctx, market, i, strategy, accountCheckInterval)
				strategyCount++
			}
		}
	}
	s.logger.Infof("Launching %d strategy!", strategyCount)
}

// choose strategy
func (s *tradingSvc) StrategyHub(ctx context.Context, m *spotExchangePB.SpotMarketInfo, idx int, strategy string, interval time.Duration) {
	switch strategy {
	case "singleExchangeMM":
		go s.SingleExchangeMM(ctx, m, idx, interval)
	}
}

/*
func (s *tradingSvc) MarketMakeDerivativeMarkets(ctx context.Context) {
	resp, err := s.derivativesClient.Markets(ctx, &derivativeExchangePB.MarketsRequest{})
	if err != nil || resp == nil {
		s.logger.Infof("Failed to get derivatives markets")
	}

	for _, market := range resp.Markets {
		go s.PostDerivativeLimitOrders(ctx, market)
		go s.CancelDerivativeLimitOrders(ctx, market)
	}
}
*/

func (s *tradingSvc) Start() (err error) {
	defer s.panicRecover(&err)

	s.logger.Infoln("Service starts")

	// main bot loop
	ctx, cancel := context.WithCancel(context.Background())
	s.Cancel = &cancel

	resp, err := s.exchangeClient.Version(ctx, &exchangePB.VersionRequest{})
	s.logger.Infof("Connected to Exchange API %s (build %s)", resp.Version, resp.MetaData["BuildDate"])

	s.DepositAllBankBalances(ctx)
	go s.MarketMakeSpotMarkets(ctx)

	return nil
}

func (s *tradingSvc) panicRecover(err *error) {
	if r := recover(); r != nil {
		*err = errors.Errorf("%v", r)

		if e, ok := r.(error); ok {
			s.logger.WithError(e).Errorln("service main loop panicked with an error")
			s.logger.Debugln(string(debug.Stack()))
		} else {
			s.logger.Errorln(r)
		}
	}
}

func (s *tradingSvc) Close() {
	// graceful shutdown if needed
	fmt.Println("\r- Ctrl+C pressed in Terminal, Stopping the strategy in 30 sec")
	(*s.Cancel)()
	time.Sleep(time.Second * 30)
	ctx := context.Background()
	s.CancelAllSpotOrders(ctx)
	os.Exit(1)
}

func (s *tradingSvc) CancelAllSpotOrders(ctx context.Context) {
	sender := s.cosmosClient.FromAddress()
	subaccountID := defaultSubaccount(sender)
	resp, err := s.spotsClient.Markets(ctx, &spotExchangePB.MarketsRequest{})
	if err != nil || resp == nil {
		message := fmt.Sprintf("❌ Failed to get spot markets when shutting down the app, need MANUALLY CANCEL orders after seeing this err: %s\n", err.Error())
		s.logger.Errorln(message)
		go s.SendCritialAlertToDiscord(message)
		return
	}
	for _, market := range resp.Markets {
		for _, symbol := range s.injSymbols {
			if symbol == market.Ticker {
				respOrders, err := s.spotsClient.Orders(ctx, &spotExchangePB.OrdersRequest{
					SubaccountId: subaccountID.Hex(),
					MarketId:     market.MarketId,
				})
				if err != nil {
					message := fmt.Sprintf("❌ Error while fetching %s spot orders when shutting down the app, need MANUALLY CANCEL orders after seeing this err: %s\n", market.Ticker, err.Error())
					s.logger.Errorln(message)
					go s.SendCritialAlertToDiscord(message)
					continue

				}
				msgs := make([]cosmtypes.Msg, 0)
				for _, order := range respOrders.Orders {
					msg := &exchangetypes.MsgCancelSpotOrder{
						Sender:       sender.String(),
						MarketId:     market.MarketId,
						SubaccountId: subaccountID.Hex(),
						OrderHash:    order.OrderHash,
					}
					msgs = append(msgs, msg)
				}
				s.HandleOrdersCancelingWhenAppClose(
					len(msgs),
					msgs,
					market.Ticker,
				)
			}
		}
	}
}

func (s *tradingSvc) SendRegularInfoToDiscord(message string) {
	if !s.sendAlert {
		return
	}
	wa, err := discordhook.NewWebhookAPI(000, "xxx", true, nil)
	if err != nil {
		s.logger.Errorln("Failed to send regular info to discord!")
	}

	_, err = wa.Execute(nil, &discordhook.WebhookExecuteParams{
		Content: message,
	}, nil, "")
	if err != nil {
		s.logger.Errorln("Failed to send regular info to discord!")
	}
}

func (s *tradingSvc) SendCritialAlertToDiscord(message string) {
	if !s.sendAlert {
		return
	}
	wa, err := discordhook.NewWebhookAPI(000, "xxx", true, nil)
	if err != nil {
		s.logger.Errorln("Failed to send critical alert to discord!")
	}

	_, err = wa.Execute(nil, &discordhook.WebhookExecuteParams{
		Content: message,
	}, nil, "")
	if err != nil {
		s.logger.Errorln("Failed to send critical alert to discord!")
	}
}
