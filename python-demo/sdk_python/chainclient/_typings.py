import sys

from typing import Literal, TypedDict


# Valid transaction broadcast modes for the `POST /txs` endpoint of the
# Cosmos REST API.
SyncMode = Literal["sync", "async", "block"]

OrderType = Literal["UNSPECIFIED", "BUY", "SELL","STOP_BUY","STOP_SELL","TAKE_BUY","TAKE_SELL"]

class Wallet(TypedDict):
    seed: str
    derivation_path: str
    private_key: bytes
    public_key: bytes
    address: str
