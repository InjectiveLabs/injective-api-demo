package main

import (
	"context"
	"os"
	"time"

	banktypes "github.com/cosmos/cosmos-sdk/x/bank/types"

	cli "github.com/jawher/mow.cli"
	rpchttp "github.com/tendermint/tendermint/rpc/client/http"
	"github.com/xlab/closer"
	log "github.com/xlab/suplog"

	"go-bot-demo/trading"

	chainclient "github.com/InjectiveLabs/sdk-go/chain/client"
	chaintypes "github.com/InjectiveLabs/sdk-go/chain/exchange/types"
	accountsPB "github.com/InjectiveLabs/sdk-go/exchange/accounts_rpc/pb"
	derivativeExchangePB "github.com/InjectiveLabs/sdk-go/exchange/derivative_exchange_rpc/pb"
	exchangePB "github.com/InjectiveLabs/sdk-go/exchange/exchange_rpc/pb"
	oraclePB "github.com/InjectiveLabs/sdk-go/exchange/oracle_rpc/pb"
	spotExchangePB "github.com/InjectiveLabs/sdk-go/exchange/spot_exchange_rpc/pb"
)

// tradingCmd action runs the service
//
// $ injective-trading-bot start
func tradingCmd(cmd *cli.Cmd) {
	// orchestrator-specific CLI options
	var (
		// Cosmos params
		cosmosChainID   *string
		cosmosGRPC      *string
		tendermintRPC   *string
		cosmosGasPrices *string

		// Cosmos Key Management
		cosmosKeyringDir     *string
		cosmosKeyringAppName *string
		cosmosKeyringBackend *string

		cosmosKeyFrom       *string
		cosmosKeyPassphrase *string
		cosmosPrivKey       *string
		cosmosUseLedger     *bool

		// Exchange API params
		exchangeGRPC *string

		// Metrics
		statsdPrefix   *string
		statsdAddr     *string
		statsdStuckDur *string
		statsdMocking  *string
		statsdDisabled *string

		// Trading parameters
		injSymbols    *[]string
		maxOrderValue *[]float64
	)

	initCosmosOptions(
		cmd,
		&cosmosChainID,
		&cosmosGRPC,
		&tendermintRPC,
		&cosmosGasPrices,
	)

	initCosmosKeyOptions(
		cmd,
		&cosmosKeyringDir,
		&cosmosKeyringAppName,
		&cosmosKeyringBackend,
		&cosmosKeyFrom,
		&cosmosKeyPassphrase,
		&cosmosPrivKey,
		&cosmosUseLedger,
	)

	initExchangeOptions(
		cmd,
		&exchangeGRPC,
	)

	initStatsdOptions(
		cmd,
		&statsdPrefix,
		&statsdAddr,
		&statsdStuckDur,
		&statsdMocking,
		&statsdDisabled,
	)

	initTradingOptions(
		cmd,
		&injSymbols,
		&maxOrderValue,
	)

	cmd.Action = func() {
		// ensure a clean exit
		defer closer.Close()

		startMetricsGathering(
			statsdPrefix,
			statsdAddr,
			statsdStuckDur,
			statsdMocking,
			statsdDisabled,
		)

		if *cosmosUseLedger {
			log.Fatalln("cannot really use Ledger for trading service loop, since signatures msut be realtime")
		}

		senderAddress, cosmosKeyring, err := initCosmosKeyring(
			cosmosKeyringDir,
			cosmosKeyringAppName,
			cosmosKeyringBackend,
			cosmosKeyFrom,
			cosmosKeyPassphrase,
			cosmosPrivKey,
			cosmosUseLedger,
		)
		if err != nil {
			log.WithError(err).Fatalln("failed to init Cosmos keyring")
		}

		log.Infoln("Using Cosmos Sender", senderAddress.String())

		clientCtx, err := chainclient.NewClientContext(*cosmosChainID, senderAddress.String(), cosmosKeyring)
		if err != nil {
			log.WithError(err).Fatalln("failed to initialize cosmos client context")
		}
		clientCtx = clientCtx.WithNodeURI(*tendermintRPC)
		tmRPC, err := rpchttp.New(*tendermintRPC, "/websocket")
		if err != nil {
			log.WithError(err).Fatalln("failed to connect to tendermint RPC")
		}
		clientCtx = clientCtx.WithClient(tmRPC)

		daemonClient, err := chainclient.NewCosmosClient(clientCtx, *cosmosGRPC, chainclient.OptionGasPrices(*cosmosGasPrices))
		if err != nil {
			log.WithError(err).WithFields(log.Fields{
				"endpoint": *cosmosGRPC,
			}).Fatalln("failed to connect to daemon, is injectived running?")
		}
		closer.Bind(func() {
			daemonClient.Close()
		})

		log.Infoln("Waiting for GRPC services")
		time.Sleep(1 * time.Second)

		daemonWaitCtx, cancelWait := context.WithTimeout(context.Background(), time.Minute)
		daemonConn := daemonClient.QueryClient()
		waitForService(daemonWaitCtx, daemonConn)
		cancelWait()

		exchangeWaitCtx, cancelWait := context.WithTimeout(context.Background(), time.Minute)
		exchangeConn, err := grpcDialEndpoint(*exchangeGRPC)
		if err != nil {
			log.WithError(err).WithFields(log.Fields{
				"endpoint": *exchangeGRPC,
			}).Fatalln("failed to connect to API, is injective-exchange running?")
		}
		waitForService(exchangeWaitCtx, exchangeConn)
		cancelWait()

		svc := trading.NewService(
			daemonClient,
			chaintypes.NewQueryClient(daemonConn),
			banktypes.NewQueryClient(daemonConn),
			accountsPB.NewInjectiveAccountsRPCClient(exchangeConn),
			exchangePB.NewInjectiveExchangeRPCClient(exchangeConn),
			spotExchangePB.NewInjectiveSpotExchangeRPCClient(exchangeConn),
			derivativeExchangePB.NewInjectiveDerivativeExchangeRPCClient(exchangeConn),
			oraclePB.NewInjectiveOracleRPCClient(exchangeConn),
			*injSymbols,
			*maxOrderValue,
		)
		closer.Bind(func() {
			svc.Close()
		})

		go func() {
			if err := svc.Start(); err != nil {
				log.Errorln(err)

				// signal there that the app failed
				os.Exit(1)
			}
		}()

		closer.Hold()
	}
}
