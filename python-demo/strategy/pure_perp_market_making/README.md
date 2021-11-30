# Pure Perp Market Making Demo
## Prerequisite
A change in TOB prices will trigger the following actions:
1. Cancel existing orders:

2. Placing new orders will be one of the following actions:
	1. Places one bid order and one ask order on injective simultaneously, both base asset is greater than minimum base asset balance and quote asset is greater than minimum quote asset balance.
	2. Only places one bid order, if the quote asset balance is greater than the minimum, and the base asset balance is smaller than the minimum base asset balance.
	3. Only places one ask order, if the base asset balance is greater than the minimum, and the quote asset balance is smaller than the minimum quote asset balance.
	4. Do not do anything.

## How to run demo

1. Modify values in `cross_exchange_market_making` in `python_demo/config/configs.ini`, 

	[cross_exchange_market_making]

	strategy_name: your strategy name

	inj_key: input your injection key

```bash
git clone https://github.com/InjectiveLabs/sdk-python.git
python setup.py install
```
## Decimal


One thing you may need to pay more attention to is how to deal with decimals in injective exchange. As we all known, different crypto currecies require diffrent decimal precisions. Separately, ERC-20 tokens (e.g. INJ) have decimals of 18 or another number (like 6 for USDT and USDC).  So in injective system that means **having 1 INJ is 1e18 inj** and that **1 USDT is actually 100000 peggy0xdac17f958d2ee523a2206206994597c13d831ec7**.



## Suggestions

Feel free to contact me when you have some errors.

And there are a few suggestions on how to report demo or API  issues.

1. before creating any issue, please make sure it is not a duplicate from existing ones
2. open an issue from injective-exchange `injective_api_demo` directly and label these issues properly with (bugs, enhancement, features, etc), and mentioned `python_demo` in title.
3. for each issue, please explain what is the issue, how to reproduce it, and present enough proofs (logs, screen shots, raw responses, etc)
4. let's always go extra one mile when reporting any issues since developer will likely spend more time on fixing those.

