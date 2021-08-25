# python _sdk_demo

| Time       | Author | Email                        |
| ---------- | ------ | ---------------------------- |
| 2021-07-20 | QIU    | kaitao@injectiveprotocol.com |

[toc]

## Prerequisite

python 3.7+

### Install injective python_sdk package

```bash
pip install injective-py
```

You could find more infomation about injective-py in https://pypi.org/project/injective-py/ or read source code from https://github.com/InjectiveLabs/sdk-python

## How to run example in sdk_python

```bash
cd /path/to/injective_py
python /path/to/exchange_api_example/exchange.py # python 3.7+
```

And you can see the avaliable markets from terminal, and the hexadecimal string is the **market id** which may be useful for connecting to market and send requests.

![example](README.assets/example.png)

Then, you can send an order in your dex front-end(default local address is localhost:3000, testnet is testnet-sentry0.injective.network)

## How to run demo

Modify environment value in `market_making_demo.json`

```bash
python pure_market_making_demo.py
```

## What does demo do

Demo with default json setting is a simple **INJUSDT** pure market-making strategy, which places several orders at the price of 1% above and below the `mid_price`(`mid_price = (bid_price_1 + ask_price_1)/2`), and then cancel all orders and replace them according to new `mid_price` every 10s.

So far, implemented trasanction-related functions include `send_limit_order`, `cancel_order`, `semd_limit_order_in_batch`, `cancel_order_in_batch`.You can add more features in `sdk_python/chain_client/_transactions.py` according to the source code of repo `injective-core`. And we will add more features and update `sdk-python` once it has be done.

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
