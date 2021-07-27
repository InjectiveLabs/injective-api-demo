
# Copyright 2021 Injective Labs
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# import sdk_python.exchange_api as exchange_api

import asyncio
import logging
import os
import pdb
import sys
import grpc

from constant import *

_current_dir = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(_current_dir, "sdk_python")
EXCHANGE_API_PATH = os.path.join(SDK_PATH, "exchange_api")
print("sdk_python directory:{}".format(SDK_PATH))
sys.path.insert(0, EXCHANGE_API_PATH)

print("exchange api directory:{}".format(EXCHANGE_API_PATH))

# injective_spot_exchange_rpc.SpotLimitOrder

import injective_accounts_rpc_pb2_grpc as accounts_rpc_grpc
import injective_accounts_rpc_pb2 as accounts_rpc_pb
import injective_spot_exchange_rpc_pb2_grpc as spot_exchange_rpc_grpc
import injective_spot_exchange_rpc_pb2 as spot_exchange_rpc_pb
import injective_exchange_rpc_pb2_grpc as exchange_rpc_grpc
import injective_exchange_rpc_pb2 as exchange_rpc_pb

class MarketMaker(object):
    def __init__(self, account_id: str, spot_symbol: str, spot_market_id=None):
        self.acct_id = account_id
        self.spot_symbol = spot_symbol + '_SPOT'
        if spot_market_id is not None:
            self.spot_market_id = spot_market_id
        else:
            try:
                self.spot_market_id = eval(self.spot_symbol)
            except ValueError as e:
                if e.__cause__:
                    print('Cause:{}'.format(e.__cause__))
                raise RuntimeError from e
        print("symbol:{}, market_id:{}".format(
            self.spot_symbol, self.spot_market_id))

    async def get_trading_request(self) -> spot_exchange_rpc_pb.TradesResponse:
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)

            mresp = await spot_exchange_rpc.Trades(spot_exchange_rpc_pb.TradesRequest(market_id=self.spot_market_id))
            print("---Trade history of {}---".format(self.spot_symbol))
            print(type(mresp))
            for trade in mresp.trades:
                print("timestamp:{}\tdirection:{}\tprice:{} quantity:{}\tfee:{}\texecution_type:{}".format(
                    trade.price.timestamp, trade.trade_direction, trade.price.price, trade.price.quantity,
                    trade.fee, trade.trade_execution_type))
            print("-----------------------------------")
            return mresp

    async def get_tick_info(self) -> spot_exchange_rpc_pb.MarketRequest:
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            mresp = await spot_exchange_rpc.Market(spot_exchange_rpc_pb.MarketRequest(market_id=self.spot_market_id))
            print(mresp)
            return mresp

    async def account_steam(self):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:

            # accounts_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(channel)
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)

            # # my account
            # acct_id = "0xbdAEdEc95d563Fb05240d6e01821008454c24C36000000000000000000000000"
            # # default account
            # # acct_id = "0xaf79152ac5df276d9a8e1e2e22822f9713474902000000000000000000000000"
            ord_direction = "buy"
            sub_balance_stream = accounts_exchange_rpc.StreamSubaccountBalance(
                accounts_rpc_pb.SubaccountBalance(subaccount_id=self.acct_id))

            async for sub_balance in sub_balance_stream:
                # acc = await accounts_exchange_rpc.SubaccountOrderSummary(accounts_rpc_pb.SubaccountOrderSummaryRequest(subaccount_id=acct_id, order_direction=ord_direction))
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Order Update:", sub_balance)

    async def buy(self, price, quantity):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            order_request = spot_exchange_rpc_pb.SpotLimitOrder(
                order_side='buy', market_id=self.market_id, subaccount_id=self.acct_id, price=price, quantity=quantity)
            order_return = spot_exchange_rpc.Order(order_request)
            print(order_return)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    acct_id = "0xbdAEdEc95d563Fb05240d6e01821008454c24C36000000000000000000000000"
    mm = MarketMaker(acct_id, 'INJUSDT')
    # asyncio.get_event_loop().run_until_complete(mm.get_trading_request())
    # asyncio.get_event_loop().run_until_complete(mm.get_tick_info())
    # asyncio.get_event_loop().run_until_complete(mm.account_steam())
    asyncio.get_event_loop().run_until_complete(mm.buy(0.1, 100))
