# Pure Perp Market Making Demo

## What does cross exchange market marking demo do?

This is a simplified InjectiveProtocol-Binance cross-exchange market strategy demo that compares TOB prices on Injective and Binance. 

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

	private_key: input your private key

	base_asset: base asset (e.g., "inj" in 'inj/usdt')

	quote_asset: quote asset (e.g., "usdt" in 'inj/usdt')

Modify environment value in `python_demo/config/configs.ini`, then

	min_quote_asset_balance: your minimum base asset balance (e.g., 20)

	min_order_size: minimum order size (e.g., 0.1, 1)

	is_mainnet: use mainnet (e.g., false)


2. `python start.py`



## Suggestions

Feel free to contact me when you have some errors.

And there are a few suggestions on how to report demo or API  issues.

1. before creating any issue, please make sure it is not a duplicate from existing ones
2. open an issue from injective-exchange `injective_api_demo` directly and label these issues properly with (bugs, enhancement, features, etc), and mentioned `python_demo` in title.
3. for each issue, please explain what is the issue, how to reproduce it, and present enough proofs (logs, screen shots, raw responses, etc)
4. let's always go extra one mile when reporting any issues since developer will likely spend more time on fixing those.
