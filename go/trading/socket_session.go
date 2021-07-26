package trading

import (
	"bytes"
	"context"
	"time"

	log "github.com/xlab/suplog"
)

func (s *tradingSvc) BinanceTickerSession(ctx context.Context, single *SingleExchangeMM, product string, idx int, ErrCh *chan map[string]interface{}) {
	var writing bool = false
	var ticker map[string]interface{}
	bookticker := make(chan map[string]interface{}, 50)
	go func(logger *log.Logger, bookticker *chan map[string]interface{}) {
		for {
			select {
			case <-ctx.Done():
				return
			default:
				BinanceSocket(ctx, product, single.Symbol[idx], "@depth20@100ms", logger, bookticker)
				var buffer bytes.Buffer
				buffer.WriteString("Rconnect to Binance ")
				buffer.WriteString(product)
				buffer.WriteString(" partial book in 3 sec...\n")
				e := make(map[string]interface{})
				e["critical"] = false
				e["count"] = false
				e["wait"] = 3
				e["message"] = buffer.String()
				(*ErrCh) <- e

				time.Sleep(time.Second * 3)
			}
		}
	}(&s.logger, &bookticker)
	Insert := time.NewTicker(time.Second * s.dataCenter.UpdateInterval)
	defer Insert.Stop()
	go func(Insert *time.Ticker) {
		for {
			select {
			case <-ctx.Done():
				return
			case <-Insert.C:
				writing = true
				bids, ok := ticker["bids"].([]interface{})
				if ok {
					single.Bids[idx] = bids
				}
				asks, ok := ticker["asks"].([]interface{})
				if ok {
					single.Asks[idx] = asks
				}
				writing = false
			default:
				time.Sleep(time.Millisecond * 500)
			}
		}
	}(Insert)
	for {
		select {
		case <-ctx.Done():
			return
		default:
			message := <-bookticker
			if !writing && len(message) != 0 {
				ticker = message
			}
		}
	}
}
