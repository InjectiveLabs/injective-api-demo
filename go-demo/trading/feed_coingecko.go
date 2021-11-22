package trading

import (
	"context"
	"encoding/json"
	"io"
	"io/ioutil"
	"net/http"
	"net/url"
	"path"
	"time"

	"github.com/InjectiveLabs/injective-trading-bot/metrics"
	"github.com/pkg/errors"
	"github.com/shopspring/decimal"
	log "github.com/xlab/suplog"
)

type FeedProvider string

type PricePuller interface {
	Provider() FeedProvider
	Symbols() []string
	Interval() time.Duration

	PullPrice(ctx context.Context) (price decimal.Decimal, err error)
}

var _ PricePuller = &coingeckoPriceFeed{}

type CoingeckoEndpointConfig struct {
	BaseURL string
}

const (
	maxRespTime                        = 15 * time.Second
	maxRespHeadersTime                 = 15 * time.Second
	maxRespBytes                       = 10 * 1024 * 1024
	FeedProviderCoingecko FeedProvider = "coingecko"
)

var zeroPrice = decimal.Decimal{}

func urlJoin(baseURL string, segments ...string) string {
	u, err := url.Parse(baseURL)
	if err != nil {
		panic(err)
	}
	u.Path = path.Join(append([]string{u.Path}, segments...)...)
	return u.String()
}

// NewCoingeckoPriceFeed returns price puller for given symbol. The price will be pulled
// from endpoint and divided by scaleFactor. Symbol name (if reported by endpoint) must match.
func NewCoingeckoPriceFeed(symbol string, interval time.Duration, endpointConfig *CoingeckoEndpointConfig) PricePuller {
	return &coingeckoPriceFeed{
		client: &http.Client{
			Transport: &http.Transport{
				ResponseHeaderTimeout: maxRespHeadersTime,
			},
			Timeout: maxRespTime,
		},
		config: checkCoingeckoConfig(endpointConfig),

		symbol:   symbol,
		interval: interval,

		logger: log.WithFields(log.Fields{
			"svc":      "oracle",
			"provider": FeedProviderCoingecko,
		}),
		svcTags: metrics.Tags{
			"provider": string(FeedProviderCoingecko),
		},
	}
}

func checkCoingeckoConfig(cfg *CoingeckoEndpointConfig) *CoingeckoEndpointConfig {
	if cfg == nil {
		cfg = &CoingeckoEndpointConfig{}
	}

	if len(cfg.BaseURL) == 0 {
		cfg.BaseURL = "https://api.coingecko.com/api/v3"
	}

	return cfg
}

type coingeckoPriceFeed struct {
	client *http.Client
	config *CoingeckoEndpointConfig

	symbol   string
	interval time.Duration

	logger  log.Logger
	svcTags metrics.Tags
}

func (f *coingeckoPriceFeed) Interval() time.Duration {
	return f.interval
}

func (f *coingeckoPriceFeed) Symbols() []string {
	return []string{
		f.symbol,
	}
}

func (f *coingeckoPriceFeed) Provider() FeedProvider {
	return FeedProviderCoingecko
}

func (f *coingeckoPriceFeed) PullPrice(ctx context.Context) (
	price decimal.Decimal,
	err error,
) {
	u, err := url.ParseRequestURI(urlJoin(f.config.BaseURL, "simple", "price"))
	if err != nil {
		f.logger.WithError(err).Fatalln("failed to parse URL")
	}

	q := make(url.Values)

	switch f.symbol {
	case "INJ/USDT":
		q.Set("ids", "injective-protocol")
		q.Set("vs_currencies", "usd")
	case "BNB/USDT":
		q.Set("ids", "binancecoin")
		q.Set("vs_currencies", "usd")
	case "DAI/USDT":
		q.Set("ids", "dai")
		q.Set("vs_currencies", "usd")
	case "USDC/USDT":
		q.Set("ids", "usd-coin")
		q.Set("vs_currencies", "usd")
	case "UNI/USDT":
		q.Set("ids", "uniswap")
		q.Set("vs_currencies", "usd")
	case "AAVE/USDT":
		q.Set("ids", "aave")
		q.Set("vs_currencies", "usd")
	case "MATIC/USDT":
		q.Set("ids", "matic-network")
		q.Set("vs_currencies", "usd")
	case "ZRX/USDT":
		q.Set("ids", "0x")
		q.Set("vs_currencies", "usd")
	case "LINK/USDT":
		q.Set("ids", "chainlink")
		q.Set("vs_currencies", "usd")
	case "YFI/USDT":
		q.Set("ids", "yearn-finance")
		q.Set("vs_currencies", "usd")
	default:
		err := errors.Errorf("unsupported symbol: %s", f.symbol)
		return zeroPrice, err
	}
	u.RawQuery = q.Encode()

	reqURL := u.String()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		f.logger.WithError(err).Fatalln("failed to create HTTP request")
	}

	resp, err := f.client.Do(req)
	if err != nil {
		err = errors.Wrapf(err, "failed to fetch price from %s", reqURL)
		return zeroPrice, err
	}

	respBody, err := ioutil.ReadAll(io.LimitReader(resp.Body, maxRespBytes))
	if err != nil {
		_ = resp.Body.Close()
		err = errors.Wrapf(err, "failed to read response body from %s", reqURL)
		return zeroPrice, err
	}
	_ = resp.Body.Close()

	var priceResp coingeckoPriceResp
	if err = json.Unmarshal(respBody, &priceResp); err != nil {
		err = errors.Wrapf(err, "failed to unmarshal response body for %s", f.symbol)
		f.logger.WithField("url", reqURL).Warningln(string(respBody))
		return zeroPrice, err
	} else if priceResp.INJ.USD > 0 {
		price = decimal.NewFromFloat(priceResp.INJ.USD)
		return price, nil
	} else if priceResp.BNB.USD > 0 {
		price = decimal.NewFromFloat(priceResp.BNB.USD)
		return price, nil
	} else if priceResp.DAI.USD > 0 {
		price = decimal.NewFromFloat(priceResp.DAI.USD)
		return price, nil
	} else if priceResp.USDC.USD > 0 {
		price = decimal.NewFromFloat(priceResp.USDC.USD)
		return price, nil
	} else if priceResp.AAVE.USD > 0 {
		price = decimal.NewFromFloat(priceResp.AAVE.USD)
		return price, nil
	} else if priceResp.UNI.USD > 0 {
		price = decimal.NewFromFloat(priceResp.UNI.USD)
		return price, nil
	} else if priceResp.MATIC.USD > 0 {
		price = decimal.NewFromFloat(priceResp.MATIC.USD)
		return price, nil
	} else if priceResp.ZRX.USD > 0 {
		price = decimal.NewFromFloat(priceResp.ZRX.USD)
		return price, nil
	} else if priceResp.LINK.USD > 0 {
		price = decimal.NewFromFloat(priceResp.LINK.USD)
		return price, nil
	} else if priceResp.YFI.USD > 0 {
		price = decimal.NewFromFloat(priceResp.YFI.USD)
		return price, nil
	}

	f.logger.Warningf("Price for [%s] fetched as zero!", f.symbol)
	return zeroPrice, nil
}

type coingeckoPriceResp struct {
	INJ struct {
		USD float64 `json:"usd"`
	} `json:"injective-protocol"`
	BNB struct {
		USD float64 `json:"usd"`
	} `json:"binancecoin"`
	DAI struct {
		USD float64 `json:"usd"`
	} `json:"dai"`
	USDC struct {
		USD float64 `json:"usd"`
	} `json:"usd-coin"`
	AAVE struct {
		USD float64 `json:"usd"`
	} `json:"aave"`
	UNI struct {
		USD float64 `json:"usd"`
	} `json:"uniswap"`
	MATIC struct {
		USD float64 `json:"usd"`
	} `json:"matic-network"`
	ZRX struct {
		USD float64 `json:"usd"`
	} `json:"0x"`
	LINK struct {
		USD float64 `json:"usd"`
	} `json:"chainlink"`
	YFI struct {
		USD float64 `json:"usd"`
	} `json:"yearn-finance"`
}
