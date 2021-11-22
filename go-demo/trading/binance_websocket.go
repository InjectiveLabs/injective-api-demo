package trading

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"math"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	"github.com/shopspring/decimal"
	log "github.com/xlab/suplog"
)

type WS struct {
	Channel       string
	OnErr         bool
	Logger        *log.Logger
	Conn          *websocket.Conn
	LastUpdatedId decimal.Decimal
}

func DecodingMap(message []byte, logger *log.Logger) (res map[string]interface{}, err error) {
	if message == nil {
		err = errors.New("the incoming message is nil")
		(*logger).Infoln(err)
		return nil, err
	}
	err = json.Unmarshal(message, &res)
	if err != nil {
		(*logger).Infoln(err)
		return nil, err
	}
	return res, nil
}

func BinanceSocket(ctx context.Context, product, symbol, channel string, logger *log.Logger, mainCh *chan map[string]interface{}) error {
	var w WS
	var duration time.Duration = 30
	w.Channel = channel
	w.Logger = logger
	w.OnErr = false
	var buffer bytes.Buffer
	switch product {
	case "spot":
		buffer.WriteString("wss://stream.binance.com:9443/ws/")
	case "swap":
		buffer.WriteString("wss://fstream3.binance.com/ws/")
	}
	buffer.WriteString(strings.ToLower(symbol))
	buffer.WriteString(w.Channel)
	url := buffer.String()
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		return err
	}
	(*logger).Infoln("Connected:", url)
	w.Conn = conn
	defer conn.Close()
	if err := w.Conn.SetReadDeadline(time.Now().Add(time.Second * duration)); err != nil {
		return err
	}
	for {
		select {
		case <-ctx.Done():
			return nil
		default:
			if w.Conn == nil {
				d := w.OutBinanceErr()
				*mainCh <- d
				message := "Binance reconnect..."
				(*logger).Infoln(message)
				return errors.New(message)
			}
			_, buf, err := conn.ReadMessage()
			if err != nil {
				d := w.OutBinanceErr()
				*mainCh <- d
				message := "Binance reconnect..."
				(*logger).Infoln(message)
				return errors.New(message)
			}
			res, err1 := DecodingMap(buf, logger)
			if err1 != nil {
				d := w.OutBinanceErr()
				*mainCh <- d
				message := "Binance reconnect..."
				(*logger).Infoln(message)
				return errors.New(message)
			}
			err2 := w.HandleBinanceSocketData(res, mainCh)
			if err2 != nil {
				d := w.OutBinanceErr()
				*mainCh <- d
				message := "Binance reconnect..."
				(*logger).Infoln(message)
				return errors.New(message)
			}
			if err := w.Conn.SetReadDeadline(time.Now().Add(time.Second * duration)); err != nil {
				return err
			}
		}
	}
}

func (w *WS) HandleBinanceSocketData(res map[string]interface{}, mainCh *chan map[string]interface{}) error {
	lastId := res["lastUpdateId"].(float64)
	newID := decimal.NewFromFloat(lastId)
	if newID.LessThan(w.LastUpdatedId) {
		m := w.OutBinanceErr()
		*mainCh <- m
		return errors.New("got error when updating lastUpdateId")
	}
	*mainCh <- res
	return nil
}

func (w *WS) OutBinanceErr() map[string]interface{} {
	w.OnErr = true
	m := make(map[string]interface{})
	return m
}

func FormatingTimeStamp(timeFloat float64) time.Time {
	sec, dec := math.Modf(timeFloat)
	return time.Unix(int64(sec), int64(dec*(1e9)))
}
