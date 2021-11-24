package trading

import (
	"context"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	cosmtypes "github.com/cosmos/cosmos-sdk/types"
	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"
	"github.com/pkg/errors"
	"github.com/shopspring/decimal"
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
	UpdateInterval       time.Duration
	InjectiveSpotAccount InjectiveSpotAccountBranch
	InjectivePositions   InjectivePositionsBranch
	InjectiveQuoteLen    int
	InjectiveQuoteAssets []InjectiveQuoteAssetsBranch
}

type InjectiveQuoteAssetsBranch struct {
	Asset              string
	Denom              string
	QuoteDenomDecimals int
	AvailableBalance   decimal.Decimal
	TotalBalance       decimal.Decimal
	mux                sync.RWMutex
}

type InjectiveSpotAccountBranch struct {
	res              *accountsPB.SubaccountBalancesListResponse
	mux              sync.RWMutex // read write lock
	Assets           []string
	Denoms           []string
	AvailableAmounts []decimal.Decimal
	TotalAmounts     []decimal.Decimal
	TotalValues      []decimal.Decimal
	LockedValues     []decimal.Decimal
}

type InjectivePositionsBranch struct {
	res *derivativeExchangePB.PositionsResponse
	mux sync.RWMutex // read write lock
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

	injSymbols    []string
	dataCenter    dataCenter
	maxOrderValue []float64
	bookSideCount []int
	leverage      []int
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
	bufferTicks []int,
	minPnlPct int,
	maxDDPct int,
	maxPositionMargin []float64,
	maxOrderValue []float64,
	bookSideCount []int,
	minBookSideCount []int,
	defaultVolPct []float64,
	riskAversion []float64,
	fillIndensity []float64,
	leverage []int,
	mysqlHost string,
	mysqlUser string,
	mysqlPwd string,
	appName string,
	cosmosGRPC []string,
	tendermintRPC []string,
	exchangeGRPC []string,
	cosmosPrivKey string,
	ip string,
) Service {
	// set log time stamp formatter
	formatter := &log.TextFormatter{
		FullTimestamp:   true,
		TimestampFormat: "2006-01-02 15:04:05.999",
	}
	logger := log.New()
	logger.SetFormatter(formatter)
	logger.WithField("svc", "trading")
	num := len(injSymbols)
	online := make([]bool, num)
	lastUpdate := make([]time.Time, num)
	return &tradingSvc{
		logger: *logger,
		svcTags: metrics.Tags{
			"svc": "sgmm_bot",
		},

		cosmosClient:        cosmosClient,
		exchangeQueryClient: exchangeQueryClient,
		bankQueryClient:     bankQueryClient,
		accountsClient:      accountsClient,
		exchangeClient:      exchangeClient,
		spotsClient:         spotsClient,
		derivativesClient:   derivativesClient,
		oracleClient:        oracleClient,
		injSymbols:          injSymbols,
		maxOrderValue:       maxOrderValue,
		bookSideCount:       bookSideCount,
		leverage:            leverage,
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

func (s *tradingSvc) MarketMakeDerivativeMarkets(ctx context.Context) {
	ErrCh := make(chan map[string]interface{}, 10)
	s.dataCenter.UpdateInterval = 2000 // milli sec
	// setting strategy
	quotes := []string{"USDT"}
	accountCheckInterval := time.Duration(20)

	// get account balances data first
	if err := s.GetInjectiveSpotAccount(ctx); err != nil {
		s.logger.Infof("Failed to get Injective account")
		return
	}
	resp, err := s.spotsClient.Markets(ctx, &spotExchangePB.MarketsRequest{})
	if err != nil || resp == nil {
		s.logger.Infof("Failed to get spot markets")
		return
	}

	s.InitialInjectiveAccountBalances(quotes, resp)
	s.InitialInjAssetWithDenom(quotes, resp)

	go s.UpdateInjectiveSpotAccountSession(ctx, accountCheckInterval, &ErrCh)

	if err := s.GetInjectivePositions(ctx); err != nil {
		s.logger.Infof("Failed to get Injective positions")
		return
	}
	go s.UpdateInjectivePositionSession(ctx, accountCheckInterval, &ErrCh)

	respDerivative, err := s.derivativesClient.Markets(ctx, &derivativeExchangePB.MarketsRequest{})
	if err != nil || respDerivative == nil {
		s.logger.Infof("Failed to get derivative markets")
		return
	}

	var strategyCount int = 0
	for _, market := range respDerivative.Markets {
		var adjTicker string
		if strings.Contains(market.Ticker, " ") {
			tmp := strings.Split(market.Ticker, " ")
			if tmp[1] != "PERP" || len(tmp) != 2 {
				continue
			}
			adjTicker = tmp[0]
		}
		for i, symbol := range s.injSymbols {
			if symbol == adjTicker {
				go s.SingleExchangeMM(ctx, market, i, accountCheckInterval, &ErrCh)
				strategyCount++
			}
		}
	}
	s.logger.Infof("Launching %d strategy!", strategyCount)
}

func (s *tradingSvc) Start() (err error) {
	defer s.panicRecover(&err)
	// main bot loop
	ctx, cancel := context.WithCancel(context.Background())
	s.Cancel = &cancel
	s.DepositAllBankBalances(ctx)
	go s.MarketMakeDerivativeMarkets(ctx)
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
	(*s.Cancel)()
}
