import asyncio
import logging
import os
import pdb
import sys
import grpc


_current_dir = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(_current_dir, "sdk_python")
CHAINCLIENT_PATH = os.path.join(SDK_PATH, "exchange_api")
print("sdk_python directory:{}".format(SDK_PATH))
sys.path.insert(0, CHAINCLIENT_PATH)

print("chainclient directory:{}".format(CHAINCLIENT_PATH))

from _transaction import Transaction
from constant import MIN_GAS_PRICE

class Trader(object):
    def __init__(self, sender_pk, acc_num, acc_seq):
        self.transaction = Transaction(privkey=sender_pk,
                                  account_num=acc_num,
                                  sequence=acc_seq,
                                  gas=100000,
                                  fee=100000 * MIN_GAS_PRICE,
                                  sync_mode="block"
    @staticmethod
    def post_spot_market_order(transaction, sender, order):
        pass
    
    @staticmethod
    def post_spot_limit_order(sender, order):
        pass
    
    @staticmethod
    def new_spot_order(subaccount_id, market_info, spot_order_data):
        pass
    
    @staticmethod
    def cancel_buy_spot_order(sender, subaccount_id, orderhash):
        pass
    
    @staticmethod
    def cancel_sell_spot_order(sender, subaccount_id, orderhash):
        pass
