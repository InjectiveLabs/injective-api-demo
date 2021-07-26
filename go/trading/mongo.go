package trading

import (
	"context"
	"time"

	log "github.com/xlab/suplog"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

const MongoPath = "mongodb://127.0.0.1:27017"

type MongoBalance struct {
	Time time.Time
	Data *BalanceData
}

type BalanceData struct {
	BaseTotalBalance      string
	QuoteTotalBalance     string
	BaseAvailableBalance  string
	QuoteAvailableBalance string
	AccountValue          string
}

func InsertBalances(collect string, data *BalanceData, logger *log.Logger) {
	ctx, _ := context.WithTimeout(context.Background(), 10*time.Second)
	client, err := mongo.Connect(ctx, options.Client().ApplyURI(MongoPath))
	if err != nil {
		(*logger).Infoln(err)
		return
	}
	defer client.Disconnect(ctx)
	Database := client.Database("inj_balance")
	collection := Database.Collection(collect)
	var input MongoBalance
	input.Time = time.Now()
	input.Data = data
	_, err = collection.InsertOne(ctx, input)
	if err != nil {
		(*logger).Infoln(err)
		return
	}
	(*logger).Infoln("insert data to db")
}

func (m *SpotMarketInfo) RecordBalances(logger *log.Logger) {
	data := BalanceData{
		BaseTotalBalance:      m.BaseTotalBalance.String(),
		BaseAvailableBalance:  m.BaseAvailableBalance.String(),
		QuoteTotalBalance:     m.QuoteTotalBalance.String(),
		QuoteAvailableBalance: m.QuoteAvailableBalance.String(),
		AccountValue:          m.AccountValue.String(),
	}
	InsertBalances(m.Ticker, &data, logger)
}
