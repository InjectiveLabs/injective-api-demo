
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

import injective_exchange_rpc_pb2 as exchange_rpc_pb
import injective_exchange_rpc_pb2_grpc as exchange_rpc_grpc
import injective_spot_exchange_rpc_pb2 as spot_exchange_rpc_pb
import injective_spot_exchange_rpc_pb2_grpc as spot_exchange_rpc_grpc

class MarketMaker(object):
    def __init__(self, spot_symbol: str, spot_market_id=None):
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
        print("symbol:{}, market_id:{}".format(self.spot_symbol, self.spot_market_id))
        

    async def get_trading_request(self) -> None:
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            exchange_rpc = exchange_rpc_grpc.InjectiveExchangeRPCStub(channel)
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)

            resp = await exchange_rpc.Version(exchange_rpc_pb.VersionRequest())
            print("-- Connected to Injective Exchange (version: %s, built %s)" %
                (resp.version, resp.meta_data["BuildDate"]))

            resp = await spot_exchange_rpc.Markets(spot_exchange_rpc_pb.MarketsRequest())
            print("\n-- Available markets:")
            for m in resp.markets:
                print(m.ticker, "=", m.market_id)

            selected_market = resp.markets[0]

            mresp = await spot_exchange_rpc.Trades(spot_exchange_rpc_pb.TradesRequest(market_id=self.spot_market_id))
            print("\n\033[1;34;40m API Response  \n")
            print("\033[0;37;40m\n-- Order Update:", mresp)
            # print(mresp.trades)
            for trade in mresp.trades:
                print("timestamp:{}\tdirection:{}\tprice:{} quantity:{}\tfee:{}\texecution_type:{}".format(\
                    trade.price.timestamp, trade.trade_direction, trade.price.price, trade.price.quantity,\
                    trade.fee, trade.trade_execution_type))

    # async def get_market_request(self) ->None:

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    mm = MarketMaker('INJUSDT')
    asyncio.get_event_loop().run_until_complete(mm.get_trading_request())
