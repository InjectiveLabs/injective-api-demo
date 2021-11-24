module go-bot-demo

go 1.17

replace github.com/gogo/protobuf => github.com/regen-network/protobuf v1.3.3-alpha.regen.1

replace github.com/btcsuite/btcutil => github.com/btcsuite/btcutil v1.0.2

replace github.com/cosmos/cosmos-sdk => github.com/InjectiveLabs/cosmos-sdk v0.44.0


require (
	github.com/InjectiveLabs/sdk-go v1.28.1
	github.com/alexcesaro/statsd v2.0.0+incompatible
	github.com/cosmos/cosmos-sdk v0.44.3
	github.com/dpong/Binance_RESTapi v1.0.3
	github.com/dpong/FTX_RESTapi v1.0.2
	github.com/ethereum/go-ethereum v1.10.11
	github.com/go-sql-driver/mysql v1.6.0
	github.com/google/go-querystring v1.1.0 // indirect
	github.com/jawher/mow.cli v1.2.0
	github.com/nickname32/discordhook v1.0.2
	github.com/pkg/errors v0.9.1
	github.com/shopspring/decimal v1.3.1
	github.com/sirupsen/logrus v1.8.1
	github.com/tendermint/tendermint v0.34.14
	github.com/xlab/closer v0.0.0-20190328110542-03326addb7c2
	github.com/xlab/suplog v1.3.1
	google.golang.org/grpc v1.41.0
	gopkg.in/alexcesaro/statsd.v2 v2.0.0 // indirect
)