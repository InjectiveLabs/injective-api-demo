ORDERTYPE_DICT = {"UNSPECIFIED": 0, "BUY": 1, "SELL": 2,
                  "STOP_BUY": 3, "STOP_SELL": 4, "TAKE_BUY": 5, "TAKE_SELL": 6}

# mainnet
price_denom_to_real_multi = {
    # BTCUSDT Perp
    "0x4ca0f92fc28be0c9761326016b5a1a2177dd6375558365116b5bdda9abc229ce": 1e-6,
    # WETHUSDT Spot
    "0xd1956e20d74eeb1febe31cd37060781ff1cb266f49e0512b446a5fafa9a16034": 1e12,
    # LINKUSDT Spot
    "0x26413a70c9b78a495023e5ab8003c9cf963ef963f6755f8b57255feb5744bf31": 1e12

}

base_quantity_denom_to_real_multi = {
    # btc, perp market dont have base asset, so multiplier is 1
    "0x4ca0f92fc28be0c9761326016b5a1a2177dd6375558365116b5bdda9abc229ce": 1,
    # WETH
    "0xd1956e20d74eeb1febe31cd37060781ff1cb266f49e0512b446a5fafa9a16034": 1e-18,
    # LINK
    "0x26413a70c9b78a495023e5ab8003c9cf963ef963f6755f8b57255feb5744bf31": 1e-18
}
quote_quantity_denom_to_real_multi = {
    # usdt
    "0x4ca0f92fc28be0c9761326016b5a1a2177dd6375558365116b5bdda9abc229ce": 1e-6,
    # usdt
    "0xd1956e20d74eeb1febe31cd37060781ff1cb266f49e0512b446a5fafa9a16034": 1e-6,
    # usdt
    "0x26413a70c9b78a495023e5ab8003c9cf963ef963f6755f8b57255feb5744bf31": 1e-6
}
denom_dict = {
    "USDT": "peggy0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "ETH": "peggy0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "LINK": "peggy0x514910771AF9Ca656af840dff83E8264EcF986CA"
}
