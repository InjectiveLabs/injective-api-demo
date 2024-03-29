## Prerequisites

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
## Decimal

One thing you may need to pay more attention to is how to deal with decimals in injective exchange. As we all known, different crypto currecies require diffrent decimal precisions. Separately, ERC-20 tokens (e.g. INJ) have decimals of 18 or another number (like 6 for USDT and USDC).  So on Injective, that means **having 1 INJ is 1e18 inj** and that **1 USDT is actually 1000000 peggy0xdac17f958d2ee523a2206206994597c13d831ec7**.

For spot markets, a price reflects the **relative exchange rate** between two tokens. If the tokens have the same decimal scale, that's great since the prices become interpretable e.g. USDT/USDC (both have 6 decimals e.g. for USDT https://etherscan.io/address/0xdac17f958d2ee523a2206206994597c13d831ec7#readContract) or MATIC/INJ (both have 18 decimals) since the decimals cancel out.  Prices however start to look wonky once you have exchanges between two tokens of different decimals, which unfortunately is most pairs with USDT or USDC denominations.  As such, injective-py has simple utility functions that maintain a hardcoded dictionary for conversions and you can also achieve such utilities by yourself (e.g. you can use external API like Alchemy's getTokenMetadata to fetch decimal of base and quote asset).

So for INJ/USDT of 6.9, the price you end up getting is 6.9*10^(6 - 18) = 6.9e-12.  Note that this market also happens to have a MinPriceTickSize of 1e-15. This makes sense since since it's defining the minimum price increment of the relative exchange of INJ to USDT.  Note that this market also happens to have a MinQuantityTickSize of 1e15. This also makes sense since it refers to the minimum INJ quantity tick size each order must have, which is 1e15/1e18 = 0.001 INJ.

## Suggestions

Feel free to create an issue or contact API support if you have any errors.

A few suggestions on reporting demo or API issues.

1. Before creating any issue, please make sure it is not a duplicate of an existing issue
2. Open an issue on this repo and label these issues properly with (bugs, enhancement, features, etc), and mentioned `python_demo` in title.
3. For each issue, please explain the issue, how to reproduce it, and present enough proofs (logs, screen shots, raw responses, etc)
4. Going the extra mile is appreciated when reporting any issues as it makes resolving the issue much easier and more efficient.

