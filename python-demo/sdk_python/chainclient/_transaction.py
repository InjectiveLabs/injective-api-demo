import base64
import hashlib
import json
from typing import Any, Dict, List

import ecdsa
import sha3

from chainclient._wallet import DEFAULT_BECH32_HRP, privkey_to_address, privkey_to_pubkey
from chainclient._typings import SyncMode
from chainclient._typings import OrderType


class Transaction:
    """A Cosmos transaction.

    After initialization, one or more messages can be added by
    calling the `add_*` methods. Finally, call `get_signed()`
    to get a signed transaction that can be posted to the `POST /txs`
    endpoint of the Cosmos REST API.
    """

    def __init__(
        self,
        *,
        privkey: bytes,
        account_num: int,
        sequence: int,
        fee: int,
        gas: int,
        fee_denom: str = "inj",
        memo: str = "",
        chain_id: str = "injective-1",
        hrp: str = DEFAULT_BECH32_HRP,
        sync_mode: SyncMode = "block",
    ) -> None:
        self._privkey = privkey
        self._account_num = account_num
        self._sequence = sequence
        self._fee = fee
        self._fee_denom = fee_denom
        self._gas = gas
        self._memo = memo
        self._chain_id = chain_id
        self._hrp = hrp
        self._sync_mode = sync_mode
        self._msgs: List[dict] = []

    # Cosmos SDK • Bank Module

    def add_cosmos_bank_msg_send(self, recipient: str, amount: int, denom: str = "inj") -> None:
        msg = {
            "type": "cosmos-sdk/MsgSend",
            "value": {
                "from_address": privkey_to_address(self._privkey, hrp=self._hrp),
                "to_address": recipient,
                "amount": [{"denom": denom, "amount": str(amount)}],
            },
        }
        self._msgs.append(msg)

    # Injective • Exchange Module

    def add_exchange_msg_deposit(self, subaccount: str, amount: int, denom: str = "inj") -> None:
        msg = {
            "type": "exchange/MsgDeposit",
            "value": {
                "sender": privkey_to_address(self._privkey, hrp=self._hrp),
                "subaccount_id": subaccount,
                "amount": {"denom": denom, "amount": str(amount)},
            },
        }
        self._msgs.append(msg)

    def add_exchange_msg_withdraw(self, subaccount: str, amount: int, denom: str = "inj") -> None:
        msg = {
            "type": "exchange/MsgWithdraw",
            "value": {
                "sender": privkey_to_address(self._privkey, hrp=self._hrp),
                "subaccount_id": subaccount,
                "amount": {"denom": denom, "amount": str(amount)},
            },
        }
        self._msgs.append(msg)

    def add_exchange_msg_cancel_spot_order(self, subaccount: str, market_id: str, order_hash: str) -> None:
        msg = {
            "type": "exchange/MsgCancelSpotOrder",
            "value": {
                "sender": privkey_to_address(self._privkey, hrp=self._hrp),
                "subaccount_id": subaccount,
                "market_id": market_id,
                "order_hash": order_hash,
            },
        }
        self._msgs.append(msg)

#     type SpotOrder struct {
# 	// market_id represents the unique ID of the market
# 	MarketId string `protobuf:"bytes,1,opt,name=market_id,json=marketId,proto3" json:"market_id,omitempty"`
# 	// order_info contains the information of the order
# 	OrderInfo OrderInfo `protobuf:"bytes,2,opt,name=order_info,json=orderInfo,proto3" json:"order_info"`
# 	// order types
# 	OrderType OrderType `protobuf:"varint,3,opt,name=order_type,json=orderType,proto3,enum=injective.exchange.v1beta1.OrderType" json:"order_type,omitempty"`
# 	// trigger_price is the trigger price used by stop/take orders
# 	TriggerPrice *github_com_cosmos_cosmos_sdk_types.Dec `protobuf:"bytes,4,opt,name=trigger_price,json=triggerPrice,proto3,customtype=github.com/cosmos/cosmos-sdk/types.Dec" json:"trigger_price,omitempty"`
# }
    def add_exchange_msg_create_spot_limit_order(self, subaccount_id: str,  market_id: str, fee_recipient: str, price: int, quantity: int, order_type: OrderType, trigger_price: int) -> None:
        msg = {
            "type": "exchange/MsgCreateSpotLimitOrder",
            "value": {
                "sender": privkey_to_address(self._privkey, hrp=self._hrp),
                "order": {
                    'market_id': market_id,
                    'order_info': {
                        'subaccount_id': subaccount_id,
                        'fee_recipient': fee_recipient,
                        'price': str(price),
                        'quantity': str(quantity),
                    },
                    'order_type': order_type,
                    "trigger_price": trigger_price,
                },
            }
        }
        self._msgs.append(msg)


    def get_signed(self) -> str:
        pubkey = privkey_to_pubkey(self._privkey)
        base64_pubkey = base64.b64encode(pubkey).decode("utf-8")
        signed_tx = {
            "tx": {
                "msg": self._msgs,
                "fee": {
                    "gas": str(self._gas),
                    "amount": [{"denom": self._fee_denom, "amount": str(self._fee)}],
                },
                "memo": self._memo,
                "signatures": [
                    {
                        "signature": self._sign(),
                        "pub_key": {"type": "injective/PubKeyEthSecp256k1", "value": base64_pubkey},
                        "account_number": str(self._account_num),
                        "sequence": str(self._sequence),
                    }
                ],
            },
            "mode": self._sync_mode,
        }
        return json.dumps(signed_tx, separators=(",", ":"))

    def _sign(self) -> str:
        message_str = json.dumps(
            self._get_sign_message(), separators=(",", ":"), sort_keys=True)
        message_bytes = message_str.encode("utf-8")

        privkey = ecdsa.SigningKey.from_string(
            self._privkey, curve=ecdsa.SECP256k1)
        signature_compact_keccak = privkey.sign_deterministic(
            message_bytes, hashfunc=sha3.keccak_256, sigencode=ecdsa.util.sigencode_string_canonize
        )
        signature_base64_str = base64.b64encode(
            signature_compact_keccak).decode("utf-8")
        return signature_base64_str

    def _get_sign_message(self) -> Dict[str, Any]:
        return {
            "chain_id": self._chain_id,
            "account_number": str(self._account_num),
            "fee": {
                "gas": str(self._gas),
                "amount": [{"amount": str(self._fee), "denom": self._fee_denom}],
            },
            "memo": self._memo,
            "sequence": str(self._sequence),
            "msgs": self._msgs,
        }
