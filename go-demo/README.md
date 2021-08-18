# injective-api-demo-go

|   Author   |           Email           |
|------------|---------------------------|
|Po Wen Perng|powen@injectiveprotocol.com|

## Prerequisite
go 1.16+

## How to run demo
This demo is a single exchange market making bot by using go-sdk.

The simple demo of go-sdk you can check [here](https://github.com/InjectiveLabs/injective-api-demo/tree/go_sdk_demo).

To set up the environment, you can check file **.env.example**.

Once setting up the environment, change the file name from *.env.example* to **.env**

Then 

```bash
$ cd /path/to/injective-api-demo/go
$ make install
$ ./injective-trading-bot.sh
```

## How it works

Based on some market fair value generation, this demo places orders on both buy and sell side based on your inventory conditions.

The reference price is from *Binance* partial book data.

You can find out all the detail from /path/to/injective-api-demo/go-demo/trading.

The main loop logic is in singleExchangeMM.go

The strategy logic is in mm_strategy.go

Orders managing logic is in inj_orders_engine.go

Injective stream data handling logic is in inj_stream.go

Feel free to do adjustments to fit your own needs.



