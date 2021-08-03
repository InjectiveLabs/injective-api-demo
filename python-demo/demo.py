import asyncio
import json
import logging
import os
import pdb
import sys
import typing
import aiohttp
import grpc

from constant import *

_current_dir = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(_current_dir, "sdk_python")
sys.path.insert(0, SDK_PATH)



import exchange_api.injective_accounts_rpc_pb2 as accounts_rpc_pb
import exchange_api.injective_accounts_rpc_pb2_grpc as accounts_rpc_grpc
import exchange_api.injective_exchange_rpc_pb2 as exchange_rpc_pb
import exchange_api.injective_exchange_rpc_pb2_grpc as exchange_rpc_grpc
import exchange_api.injective_spot_exchange_rpc_pb2 as spot_exchange_rpc_pb
import exchange_api.injective_spot_exchange_rpc_pb2_grpc as spot_exchange_rpc_grpc
from chainclient._transaction import Transaction as Transaction
from chainclient._wallet import generate_wallet as generate_wallet
from chainclient._wallet import privkey_to_address as privkey_to_address
from chainclient._wallet import privkey_to_pubkey as privkey_to_pubkey
from chainclient._wallet import pubkey_to_address as pubkey_to_address
from chainclient._wallet import seed_to_privkey as seed_to_privkey


class MarketMaker(object):
    def __init__(self, account_id: str, spot_symbol: str, seed: str, spot_market_id=None):
        self.acct_id = account_id
        # self.private_key = private_key
        self.seed = seed
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
        self.private_key = seed_to_privkey(self.seed)
        self.sender_acc_addr = privkey_to_address(self.private_key)
        print("Sender Account:", self.sender_acc_addr)
        print("sender private key:{}".format(self.private_key))


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
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)

            ord_direction = "buy"
            sub_balance_stream = accounts_exchange_rpc.StreamSubaccountBalance(
                accounts_rpc_pb.SubaccountBalance(subaccount_id=self.acct_id))

            async for sub_balance in sub_balance_stream:
                print("\n\033[1;34;40m API Response  \n")
                print("\033[0;37;40m\n-- Order Update:", sub_balance)

    async def send_tx_test(self):
        sender_pk = seed_to_privkey(
            "physical page glare junk return scale subject river token door mirror title")
        sender_acc_addr = privkey_to_address(sender_pk)
        print("Sender Account:", sender_acc_addr)
        print("sender private key:{}".format(sender_pk))

        # To Check:
        #   $ injectived --home ./var/data/injective-888/n0 --keyring-backend test keys show user1
        #   address: inj1hkhdaj2a2clmq5jq6mspsggqs32vynpk228q3r

        acc_num, acc_seq = await self.get_account_num_seq(sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
            privkey=sender_pk,
            account_num=acc_num,
            sequence=acc_seq,
            gas=100000,
            fee=100000 * MIN_GAS_PRICE,
            chain_id = "injective-1",
            sync_mode="block"
        )
        tx.add_cosmos_bank_msg_send(
            recipient="inj1qy69k458ppmj45c3vqwcd6wvlcuvk23x0hsz58",  # maxim @ e2e-multinode
            amount=100000000000000000,  # 0.1 INJ
            denom="inj",
        )

        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))
    
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

                return resp['txhash']

    async def test_deposit(self, quantity, denom='inj'):
        acc_num, acc_seq = await self.get_account_num_seq(self.sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
            privkey=self.private_key,
            account_num=acc_num,
            sequence=acc_seq,
            gas=1000,
            fee=1000 * MIN_GAS_PRICE,
            chain_id = "injective-1",
            sync_mode="block"
        )

        tx.add_exchange_msg_deposit(self.acct_id, quantity, denom=denom)
        
        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))
    

    async def test_cancel_order(self, order_hash):
        
        acc_num, acc_seq = await self.get_account_num_seq(self.sender_acc_addr)
        print("acc_num:{} acc_seq:{}".format(acc_num, acc_seq))

        tx = Transaction(
        privkey=self.private_key,
        account_num=acc_num,
        sequence=acc_seq,
        gas=200000,
        fee=200000 * MIN_GAS_PRICE,
        chain_id = "injective-1",
        sync_mode="block"
        )

        tx.add_cancel_spot_order(self.acct_id, self.spot_market_id, order_hash)
        
        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))
    
    async def test_send_limit_order(self, price, quantity, order_type, trigger_price, fee_recipient = None):
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
        tx.add_exchange_msg_create_spot_limit_order(self.acct_id, self.spot_market_id, fee_recipient, price, quantity, order_type, trigger_price)

        tx_json = tx.get_signed()

        print('Signed Tx:', tx_json)
        print('Sent Tx:', await self.post_tx(tx_json))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    acct_id = "0xbdaedec95d563fb05240d6e01821008454c24c36000000000000000000000000"
    # private_key = "edbde3a6da2165d23c7dbfa8a5159a1253cd1a39a210aadad43296aec1e37b48"
    seed = "physical page glare junk return scale subject river token door mirror title"
    # order_hash = "0xb4879e6c13f6645a6f5383b863f2631686a57d0ca4a9c9ddab0ea7b7dcd0a9d5"
    mm = MarketMaker(acct_id, 'INJUSDT', seed)
    # asyncio.get_event_loop().run_until_complete(mm.test_send_order())

    # asyncio.get_event_loop().run_until_complete(mm.test_cancel_order(order_hash))
    asyncio.get_event_loop().run_until_complete(
        mm.test_send_limit_order("0.000000005000000000", "1222000000000000000000.000000000000000000", 2, "0.000000000000000000", "inj1cml96vmptgw99syqrrz8az79xer2pcgp0a885r"))
