# FundingArbitrage Demo

## How to run pure arbitrage demo

Modify environment value in python_demo/config/configs.ini, then

```bash
python start.py
```

## What does pure perpetual market making strategy do

| Parameter          | Required | Description                                               |
| :----------------- | -------- | --------------------------------------------------------- |
| strategy_name      | True     |                                                           |
| priv_key           | True     | private key of your account                               |
| is_mainnet         | True     | 'true' stands for mainnet;only support mainnet            |
| binance_api_key    | True     |                                                           |
| binance_api_secret | True     |                                                           |
| order_size         | True     | the max position that you wanna hold for funding strategy |
| symbol             | True     | e.g. BTCUSDT                                              |
| base_asset         | True     | e.g. BTC                                                  |
| quote_asset        | True     | e.g. USDT                                                 |

In this demo, the program will hold different positions in binance and injective exchange to arbitrage their funding rates. (**Both are USDT-M**) Since the orders in injective exchange is slightly hard to be executed than that in binance, we trade the first leg in injective in maker order type, it will post in the orderbook with closed price to bid price or ask price. Once it get filled, we will execute the second leg which is the inverse position in binance exchange.

This is a delta neutural strategy, and it will only execute when the sign of funding rates in injective exchange and binance exchange are opposite. You can change the condition in function `on_funding_rates`.

```python
    async def on_funding_rates(self):
        if self.inj_funding_rate * self.binance_funding_rate < 0:
            await self.get_address()
            self.msg_list = []
            if self.inj_funding_rate > 0 and self.net_position < self.order_size:
                # Use the most closed price in inj orderbook to execute the first leg
                await self.inj_limit_buy(self.inj_ask_price_1 - self.tick_size, (self.order_size - self.net_position))
            elif self.inj_funding_rate < 0 and self.net_position > -self.order_size:
                # Use the most closed price in inj orderbook to execute the first leg
                await self.inj_limit_sell(self.inj_bid_price_1 + self.tick_size, (self.order_size - self.net_position))
```
