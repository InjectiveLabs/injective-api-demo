# Pure Arbitrage Demo

## How to run pure arbitrage demo

Modify environment value in python_demo/config/configs.ini, then

```bash
python start.py
```

## What does pure perpetual market making strategy do

| Parameter          | Required | Description                                                                                                                    |
| :----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| strategy_name      | True     |                                                                                                                                |
| priv_key           | True     | private key of your account                                                                                                    |
| is_mainnet         | True     | 'true' stands for mainnet;only support mainnet                                                                                 |
| binance_api_key    | True     |                                                                                                                                |
| binance_api_secret | True     |                                                                                                                                |
| interval           | True     | frequency of arbitrage (in second)                                                                                             |
| arb_threshold      | True     | threshold for price gap between two exchanges<br />if current price gap is larger than threshold, do arbitrategy on both sides |
| order_size         | True     | max order size                                                                                                                 |
| re_binance_hour    | True     | interval to rebalance positions on both exchange                                                                               |
| symbol             | True     | e.g. BTCUSDT                                                                                                                   |
| base_asset         | True     | e.g. BTC                                                                                                                       |
| quote_asset        | True     | e.g. USDT                                                                                                                      |
