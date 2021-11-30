# python _sdk_demo


![](../../../logos/Logo_stacked_Brand_Black_with_space.png)


[toc]

## Prerequisite

python 3.7+

pyinjective (please install latest code in master branch from github, https://github.com/InjectiveLabs/sdk-python)

### Install injective python_sdk package

```bash
pip install injective-py
```

If you had problems while installing the injective python_sdk package, you should install the dependencies in
https://ofek.dev/coincurve/

You could find more information about injective-py in https://pypi.org/project/injective-py/

If the latest package is not uploaded to pypi, you use the following commands to update `injective-py`

```bash
git clone https://github.com/InjectiveLabs/sdk-python.git
python setup.py install
```

## How to run demo

Modify environment value in `./config/configs.ini`, then

```bash
python start.py
```

## [What does mean reversion strategy do?](https://www.cmcmarkets.com/en/trading-guides/mean-reversion)

Mean reversion in trading theorizes that prices tend to return to average levels, and extreme price moves are hard to sustain for extended periods. Traders who partake in mean reversion trading have developed many methods for capitalising on the theory. In all cases, they are betting that an extreme level — whether it be volatility, price, growth, or a technical indicator — will return to the average.

## [How to generate trading signals?](https://www.investopedia.com/trading/using-bollinger-bands-to-gauge-trends/)
1. Define a moving window with length of **n_window**.
2. Calculate the mean and standard deviation within the moving window.
3. Upper band/Lower band = mean +/- n_std * std
4. When the Price go beyond the upper/lower band, sell/buy the coin to capture the mispricing opportunities.
5. When the Price go down/up to the Mean, buy/sell the coin.
6. Move the moving window forward and repeat 1~5. 

**Strategy configs**

| Parameter | Required| Description| Links|
|:-------:|:-------:|:----------|:-----:|
|strategy_name|True|name of the strategy||
|inj_chain_addr|True|input your Injective Address||
|private_key|True|input your private key||
|fee_recipient|True|input the Injective Address to receive 40% transaction fee||
|is_mainnet|True|trading on mainnet or testnet||
|base_asset|True|In INJ/USDT, INJ is the base_asset||
|quote_asset|True|In INJ/USDT. USDT is the quote_asset||
|interval_in_second|True|trading frequency measured in second|
|n_window|True|the number of total period|[SMA](https://www.investopedia.com/terms/s/sma.asp)|
|n_std|True|the number of standard deviations|[Bollinger Bands](https://www.investopedia.com/trading/using-bollinger-bands-to-gauge-trends/)|
|order_size|True|the size of each orders||
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
