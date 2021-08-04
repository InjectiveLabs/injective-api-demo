
import asyncio
import json
import logging
import os
import sys
import typing

import aiohttp
import grpc
from apscheduler.scheduler import Scheduler

from constant import *
from utils import price_string_to_float, quantity_string_to_float, quantity_float_to_string, price_float_to_string

from chainclient._wallet import seed_to_privkey as seed_to_privkey
from chainclient._wallet import pubkey_to_address as pubkey_to_address
from chainclient._wallet import privkey_to_pubkey as privkey_to_pubkey
from chainclient._wallet import privkey_to_address as privkey_to_address
from chainclient._wallet import generate_wallet as generate_wallet
from chainclient._transaction import Transaction as Transaction
import exchange_api.injective_spot_exchange_rpc_pb2_grpc as spot_exchange_rpc_grpc
import exchange_api.injective_spot_exchange_rpc_pb2 as spot_exchange_rpc_pb
import exchange_api.injective_exchange_rpc_pb2_grpc as exchange_rpc_grpc
import exchange_api.injective_exchange_rpc_pb2 as exchange_rpc_pb
import exchange_api.injective_accounts_rpc_pb2_grpc as accounts_rpc_grpc
import exchange_api.injective_accounts_rpc_pb2 as accounts_rpc_pb

_current_dir = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(_current_dir, "sdk_python")
CONFIG_PATH = os.path.join(_current_dir, "config")

sys.path.insert(0, SDK_PATH)


class Trader(object):
    def __init__(self, account_id: str, spot_symbol: str, seed: str, base_denom, quote_denom):
        self.acct_id = account_id
        # self.private_key = private_key
        self.seed = seed
        self.spot_symbol = spot_symbol + '_SPOT'
        try:
            self.spot_market_id = eval(self.spot_symbol)
        except ValueError as e:
            if e.__cause__:
                print('Cause:{}'.format(e.__cause__))
            raise RuntimeError from e
        print("symbol:{}, market_id:{}".format(
            self.spot_symbol, self.spot_market_id))

        self.private_key = seed_to_privkey(self.seed)
        self.sender_acc_addr = privkey_to_address(self.private_key)
        print("Sender Account:", self.sender_acc_addr)
        print("sender private key:{}".format(self.private_key))

        self.base_decimals = DECIMALS_DICT[base_denom]
        self.quote_decimals = DECIMALS_DICT[quote_denom]

    async def get_market_info(self) -> spot_exchange_rpc_pb.MarketRequest:
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            mresp = await spot_exchange_rpc.Market(spot_exchange_rpc_pb.MarketRequest(market_id=self.spot_market_id))
            print(mresp)
            return mresp

    async def get_orderbook(self) -> spot_exchange_rpc_pb.OrderbookRequest:
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

            mkt_id = "0x17d9b5fb67666df72a5a858eb9b81104b99da760e3036a8243e05532d50e1c7c"  # INJ/USDT Spot
            acct_id = "0xaf79152ac5df276d9a8e1e2e22822f9713474902000000000000000000000000"

            print("\n-- Watching for order updates on market %s" %
                  selected_market.ticker)

            # Request
            mresp = await spot_exchange_rpc.Orderbook(spot_exchange_rpc_pb.OrderbookRequest(market_id=mkt_id))
            print("\n\033[1;34;40m API Response  \n")
            print("\033[0;37;40m\n-- Order Update:", mresp)
            return mresp

    async def account_steam(self):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)

            ord_direction = "buy"
            sub_balance_stream = accounts_exchange_rpc.StreamSubaccountBalance(
                accounts_rpc_pb.SubaccountBalance(subaccount_id=self.acct_id))

            async for sub_balance in sub_balance_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Order Update:", sub_balance)

    async def get_trades(self):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            acc_ord = await spot_exchange_rpc.SubaccountTradesList(
                spot_exchange_rpc_pb.SubaccountTradesListRequest(
                    subaccount_id=self.acct_id, market_id=self.spot_market_id))
            print("\n\033[1;34;40m API Response  \n")
            print("\033[0;37;40m\n-- Order Update:", acc_ord)

    async def get_orders(self):
        pass

    async def get_user_order_steam(self, order_callback):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            stream_req = spot_exchange_rpc_pb.StreamOrdersRequest(
                market_id=self.spot_market_id, subaccount_id=self.acct_id)

            orders_stream = spot_exchange_rpc.StreamOrders(stream_req)
            async for order in orders_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Order Update:", order)
                order_callback(order)

    async def get_total_market_order_steam(self):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)
            stream_req = spot_exchange_rpc_pb.StreamOrdersRequest(
                market_id=self.spot_market_id)

            orders_stream = spot_exchange_rpc.StreamOrders(stream_req)
            async for order in orders_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Order Update:", order)

    async def get_user_trade_steam(self, trade_callback):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)

            stream_req = spot_exchange_rpc_pb.StreamTradesRequest(
                market_id=self.spot_market_id, subaccount_id=self.acct_id)

            trade_stream = spot_exchange_rpc.StreamTrades(stream_req)
            async for trade in trade_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Trade Update:", trade)
                trade_callback(trade)

    async def get_total_market_trade_steam(self):
        async with grpc.aio.insecure_channel('localhost:9910') as channel:
            spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
                channel)

            stream_req = spot_exchange_rpc_pb.StreamTradesRequest(
                market_id=self.spot_market_id)

            trade_stream = spot_exchange_rpc.StreamTrades(stream_req)
            async for trade in trade_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Trade Update:", trade)

    @staticmethod
    async def get_account_num_seq(address: str) -> typing.Tuple[int, int]:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                'GET', 'http://localhost:10337/cosmos/auth/v1beta1/accounts/' + address,
                headers={'Accept-Encoding': 'application/json'},
            ) as response:
                if response.status != 200:
                    print(await response.text())
                    raise ValueError("HTTP response status", response.status)

                resp = json.loads(await response.text())
                acc = resp['account']['base_account']
                return acc['account_number'], acc['sequence']

    @ staticmethod
    async def post_tx(tx_json: str):
        async with aiohttp.ClientSession() as session:
            async with session.request(
                # 'POST', 'http://localhost:10337/cosmos/tx/v1beta1/txs', data=tx_json,
                'POST', 'http://localhost:10337/txs', data=tx_json,
                headers={'Content-Type': 'application/json'},
            ) as response:
                # print(response.text())
                if response.status != 200:
                    print(await response.text())
                    raise ValueError("HTTP response status", response.status)

                resp = json.loads(await response.text())
                if 'code' in resp:
                    print("Response:", resp)
                    raise ValueError('sdk error %d: %s' %
                                     (resp['code'], resp['raw_log']))

                # return resp['txhash']
                return resp

    async def deposit(self, quantity, denom='inj'):
        acc_num, acc_seq = await self.get_account_num_seq(self.sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
            privkey=self.private_key,
            account_num=acc_num,
            sequence=acc_seq,
            gas=1000,
            fee=1000 * MIN_GAS_PRICE,
            chain_id="injective-1",
            sync_mode="block"
        )

        tx.add_exchange_msg_deposit(self.acct_id, quantity, denom=denom)

        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))

    async def cancel_order(self, order_hash):

        acc_num, acc_seq = await self.get_account_num_seq(self.sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
            privkey=self.private_key,
            account_num=acc_num,
            sequence=acc_seq,
            gas=200000,
            fee=200000 * MIN_GAS_PRICE,
            chain_id="injective-1",
            sync_mode="block"
        )

        tx.add_cancel_spot_order(self.acct_id, self.spot_market_id, order_hash)

        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))

    async def send_limit_order(self, base_denom: str, quote_denom: str, price: float, quantity: float,
                               order_type_string: str, trigger_price: int, fee_recipient=None):
        acc_num, acc_seq = await self.get_account_num_seq(self.sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
            privkey=self.private_key,
            account_num=acc_num,
            sequence=acc_seq,
            gas=200000,
            fee=200000 * MIN_GAS_PRICE,
            chain_id="injective-1",
            sync_mode="block"
        )

        if fee_recipient == None:
            fee_recipient = self.sender_acc_addr

        price_string = price_float_to_string(
            price, self.base_decimals, self.quote_decimals)
        quantity_string = quantity_float_to_string(
            quantity, self.base_decimals)
        trigger_price_string = price_float_to_string(
            trigger_price, self.base_decimals, self.quote_decimals)
        order_type = ORDERTYPE_DICT[order_type_string]

        tx.add_exchange_msg_create_spot_limit_order(
            self.acct_id, self.spot_market_id, fee_recipient, price_string, quantity_string, order_type, trigger_price_string)

        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))


class Strategy(object):
    def __init__(self, trader: Trader, base_position, quote_position):
        self.trader = trader
        self.active_order = {}
        self.base_position = base_position
        self.quote_position = quote_position
        self.frozen_base = 0
        self.frozen_quote = 0
        asyncio.get_event_loop().run_until_complete(
            self.trader.get_user_order_steam(self.on_order))
        asyncio.get_event_loop().run_until_complete(
            self.trader.get_user_trade_steam(self.on_trade))

    def get_bid_ask_price(self):
        order_book_request = asyncio.get_event_loop(
        ).run_until_complete(self.trader.get_orderbook())
        bids = [buy for buy in order_book_request.order_book.buys]
        bids = sorted(bids, key=lambda x: x.price)

        asks = [sell for sell in order_book_request.order_book.sells]
        asks = sorted(asks, key=lambda x: x.price)

        return price_string_to_float(bids[0].price, self.base_decimals, self.quote_decimals), \
            price_string_to_float(
                asks[0].price, self.base_decimals, self.quote_decimals)

    # def on_trade(self, trade):
    #     import pdb
    #     pdb.set_trace()
    #     trade_data = trade.trade

    def on_order(self, order):
        order_data = order.order
        if order.operation_type == 'insert':
            self.active_order[order_data.order_hash] = order_data
            # maintain frozen balance
            if order_data.order_side == "sell":
                self.frozen_quote += quantity_string_to_float(
                    order_data.unfilled_quantity, self.trader.base_decimals)
            else:
                self.frozen_base += quantity_string_to_float(
                    order_data.unfilled_quantity, self.trader.base_decimals)

        elif order.operation_type == 'update' and order_data.state in ['partial_filled']:
            self.active_order[order_data.order_hash] = order_data
        elif order_data.state in ['filled']:
            self.active_order.pop(order_data.order_hash)
        elif order_data.state in ['canceled']:
            try:
                self.active_order.pop(order_data.order_hash)
                if order_data.order_side == "sell":
                    self.frozen_quote -= quantity_string_to_float(
                        order_data.unfilled_quantity, self.trader.base_decimals)
                else:
                    self.frozen_base -= quantity_string_to_float(
                        order_data.unfilled_quantity, self.trader.base_decimals)
            except KeyError as e:
                print("KeyError in self.active_order :{}".format(e))


if __name__ == '__main__':

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
        datefmt='%Y-%m-%d %A %H:%M:%S',
        filename="./log/demo_log.log",
        filemode='a'
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s  %(filename)s : %(levelname)s  %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)

    demo_config_path = os.path.join(CONFIG_PATH, "market_making_demo.json")
    with open(demo_config_path, 'r') as config_file:
        demo_config = json.load(config_file)
    logging.info("Loading config of [{}] from {}".format(
        demo_config['strategy_name'], demo_config_path))

    subaccount_id = demo_config['subaccount_id']
    seed = demo_config['seed']
    fee_recipient = demo_config['fee_recipient']
    market = demo_config['market']
    base_denom = demo_config['base_denom']
    quote_denom = demo_config['quote_denom']
    base_position = demo_config['base_position']
    quote_position = demo_config['quote_position']

    trader = Trader(subaccount_id, market, seed, base_denom, quote_denom)
    market_maker = Strategy(trader, base_position, quote_position)
    # market_maker.get_bid_ask_price()
    market_maker.on_trade()
