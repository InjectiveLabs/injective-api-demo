# spot market id
INJUSDT_SPOT = "0x17d9b5fb67666df72a5a858eb9b81104b99da760e3036a8243e05532d50e1c7c"
BNBUSDT_SPOT = "0xc1565353dad334afb6a3edd0b8ec70c4f4f716cc480df6d59927561719251924"
LINKUSDT_SPOT = "0xea0bed9ce263393e7d9ec38b6d46d584acf8bdde71077e44faf933f0010a5299"
UNIUSDT_SPOT = "0x8ec09ceda5ddc08352ef7912f1fc9365e1204e475eb00bc9738c48e978823496"
YFIUSDT_SPOT = "0x7370ee52c71c7d9f96185fa0470bbeb09afd76f724a4089063087c5a6c9bda33"
AAVEUSDT_SPOT = "0x4dd30fa439753f22ad3fa1a2aa4b0415af128b38e6a500454bb3666886040f16"
MATICUSDT_SPOT = "0x92e56c48cb313f68287d999cf970da7fe7cfeb4db21f3ee0600152d30886fe9d"
ZRXUSDT_SPOT = "0x1733fd28ac7cfe99b3235a3a92912b660596a25500dd8b94d11bffb9d264b5c9"

MIN_GAS_PRICE = 500000000

# from etherscan.io
DECIMALS_DICT = {
    "INJ": 18,  # uint8
    "USDT": 6,  # uint256
    "BNB": 18,  # uint8
    "LINK": 18,  # uint8
    "UNI": 18,  # uint8
    "AAVE": 18,  # uint8 from https://etherscan.io/token/0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9#readProxyContract
    "MATIC": 18,  # uint8
    "ZRX": 18,  # uint8
    "USDC": 6,  # uint8 from https://etherscan.io/token/0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48#readProxyContract
}


ORDERTYPE_DICT = {"UNSPECIFIED": 0, "BUY": 1, "SELL": 2,
             "STOP_BUY": 3, "STOP_SELL": 4, "TAKE_BUY": 5, "TAKE_SELL": 6}
