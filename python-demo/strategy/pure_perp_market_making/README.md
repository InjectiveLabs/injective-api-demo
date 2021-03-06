# Pure Perp Market Making Demo

## How to run pure perpetual market making demo

Modify environment value in python_demo/config/configs.ini, then

```bash
python start.py
```

## What does pure perpetual market making strategy do

Demo with default json setting is a simple Perpetual BTCUSDT pure market-making strategy, which places one bid order and one ask order around midprice `(midprice = (bid_price_1+ask_price_1) / 2)`, `placing_spread/mid_price` is fixed according to the value in configuration. And it will cancel and quote bid/ask order every interval(default is 20) seconds. **You can add more logic in strategy to manage inventory risk.**

| Parameter     | Required | Description                                                |
| ------------- | -------- | ---------------------------------------------------------- |
| strategy_name | True     |                                                            |
| priv_key      | True     | private key of your account                                |
| is_mainnet    | True     | 'true' stands for mainnet;<br />'false' stands for testnet |
| leverage      | True     | leverage for each order                                    |
| interval      | True     | frequency of placking orders( in second)                   |
| order_size    | True     |                                                            |
| spread_ratio  | True     | spread for bid and ask orders                              |
| symbol        | True     | e.g. BTCUSDT                                               |
| base_asset    | True     | e.g. BTC                                                   |
| quote_asset   | True     | e.g. USDT                                                  |

## Decimal

One thing you may need to pay more attention to is how to deal with decimals in injective exchange. As we all known, different crypto currecies require diffrent decimal precisions. Separately, ERC-20 tokens (e.g. INJ) have decimals of 18 or another number (like 6 for USDT and USDC).  So in injective system that means **having 1 INJ is 1e18 inj** and that **1 USDT is actually 100000 peggy0xdac17f958d2ee523a2206206994597c13d831ec7**.

For spot markets, a price reflects the **relative exchange rate** between two tokens. If the tokens have the same decimal scale, that's great since the prices become interpretable e.g. USDT/USDC (both have 6 decimals e.g. for USDT https://etherscan.io/address/0xdac17f958d2ee523a2206206994597c13d831ec7#readContract) or MATIC/INJ (both have 18 decimals) since the decimals cancel out.  Prices however start to look wonky once you have exchanges between two tokens of different decimals, which unfortunately is most pairs with USDT or USDC denominations.  As such, I've created some simple utility functions by keeping a hardcoded dictionary in injective-py and you can aslo achieve such utilities by yourself (e.g. you can use external API like Alchemy's getTokenMetadata to fetch decimal of base and quote asset).

So for INJ/USDT of 6.9, the price you end up getting is 6.9*10^(6 - 18) = 6.9e-12.  Note that this market also happens to have a MinPriceTickSize of 1e-15. This makes sense since since it's defining the minimum price increment of the relative exchange of INJ to USDT.  Note that this market also happens to have a MinQuantityTickSize of 1e15. This also makes sense since it refers to the minimum INJ quantity tick size each order must have, which is 1e15/1e18 = 0.001 INJ.

## Suggestions

Feel free to contact me when you have some errors.

And there are a few suggestions on how to report demo or API  issues.

1. before creating any issue, please make sure it is not a duplicate from existing ones
2. open an issue from injective-exchange `injective_api_demo` directly and label these issues properly with (bugs, enhancement, features, etc), and mentioned `python_demo` in title.
3. for each issue, please explain what is the issue, how to reproduce it, and present enough proofs (logs, screen shots, raw responses, etc)
4. let's always go extra one mile when reporting any issues since developer will likely spend more time on fixing those.
