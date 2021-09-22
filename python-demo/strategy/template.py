import asyncio
import grpc
import pyinjective.proto.exchange.injective_derivative_exchange_rpc_pb2 as derivative_exchange_rpc_pb
import pyinjective.proto.exchange.injective_derivative_exchange_rpc_pb2_grpc as derivative_exchange_rpc_grpc

import pyinjective.proto.exchange.injective_accounts_rpc_pb2 as accounts_rpc_pb
import pyinjective.proto.exchange.injective_accounts_rpc_pb2_grpc as accounts_rpc_grpc

from pyinjective.constant import Network
from pyinjective.composer import Composer as ProtoMsgComposer


from six import reraise

from core.object import TickData, OrderData, TradeData, PositionData
from util.decimal_utils import floor_to, round_to
from typing import Callable
import aiohttp
import json
from pyinjective.wallet import PrivateKey, PublicKey, Address

network = Network.testnet()


class PerpMarketManipulation(object):
    def __init__(self, setting):
        self.ticker_size = 0.001
        self.priv_key = PrivateKey.from_hex(setting["priv_key"])
        self.pub_key = self.priv_key.to_public_key()
        self.address = self.pub_key.to_address()
        self.acc_id = self.address.get_subaccount_id(index=0)
        self.sender = self.fee_recipient = self.address.to_acc_bech32()
        if setting["is_mainnet"] is False:
            self.network = Network.testnet()
        else:
            self.network = Network.mainnet()

        self.market_id = setting["market_id"]
        self.is_trading = False

    async def test_connect(self):
        self.get_market()

    """ perp market relationed function"""
    async def get_market(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            market_response = await derivative_exchange_rpc.Market(derivative_exchange_rpc_pb.MarketRequest(market_id=self.market_id))
            print("\n-- Market Update:\n", market_response)
            return market_response

    async def get_markets(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            status = "active"
            markets_response = await derivative_exchange_rpc.Markets(derivative_exchange_rpc_pb.MarketsRequest(market_status=status))
            print("\n-- Markets Update:\n", markets_response)
            return markets_response

    async def stream_market(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)

            stream_req = derivative_exchange_rpc_pb.StreamMarketRequest()
            stream_resp = derivative_exchange_rpc.StreamMarket(stream_req)
            async for market in stream_resp:
                print("\n-- Order Update:\n", market)

    """perp position related function"""
    async def get_position(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            presp = await derivative_exchange_rpc.Positions(derivative_exchange_rpc_pb.PositionsRequest(market_id=self.market_id, subaccount_id=self.acc_id))
            print("\n-- Positions Update:\n", presp)
            return presp

    async def get_liquidable_position(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            lresp = await derivative_exchange_rpc.LiquidablePositions(derivative_exchange_rpc_pb.LiquidablePositionsRequest())
            print("\n-- Liquidable Positions Update:\n", lresp)
            return lresp

    """perp order related function"""
    async def get_orders(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            ordresp = await derivative_exchange_rpc.Orders(derivative_exchange_rpc_pb.OrdersRequest(market_id=self.market_id))
            print("\n-- Orders Update:\n", ordresp)
            return ordresp

    async def get_orderbook(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            orderbookresp = await derivative_exchange_rpc.Orderbook(derivative_exchange_rpc_pb.OrderbookRequest(market_id=self.market_id))
            print("\n-- Orderbook Update:\n", orderbookresp)
            return orderbookresp

    async def stream_orderbook(self, market_id):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            stream_req = derivative_exchange_rpc_pb.StreamOrderbookRequest(
                market_id=market_id)
            stream_resp = derivative_exchange_rpc.StreamOrderbook(stream_req)
            async for orderbook in stream_resp:
                # print("\n-- Orderbook Update:", orderbook)

                tick_data = TickData()
                for i in range(5):
                    tick_data.__setattr__(
                        "ask_price_" + str(i + 1), float(orderbook.orderbook.sells[i].price)/1000000)
                    tick_data.__setattr__(
                        "bid_price_" + str(i + 1), float(orderbook.orderbook.buys[i].price)/1000000)
                    tick_data.__setattr__(
                        "ask_volume_" + str(i + 1), float(orderbook.orderbook.sells[i].quantity))
                    tick_data.__setattr__(
                        "bid_volume_" + str(i + 1), float(orderbook.orderbook.buys[i].quantity))
                tick_data.timestamp = orderbook.orderbook.sells[0].timestamp
                self.on_tick(tick_data)

    """ account related function"""
    async def get_account_order(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            subacc_ord = await derivative_exchange_rpc.SubaccountOrdersList(derivative_exchange_rpc_pb.SubaccountOrdersListRequest(subaccount_id=self.acc_id))
            print("\n-- Subaccount Orders List Update:\n", subacc_ord)

    async def get_account_trade(self):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            subacc_trades = await derivative_exchange_rpc.SubaccountTradesList(derivative_exchange_rpc_pb.SubaccountTradesListRequest(subaccount_id=self.acc_id, market_id=self.market_id))
            print("\n-- Subaccount Trades List Update:\n", subacc_trades)

    async def get_account_balance(self, subacc_id, dnm='inj'):
        async with grpc.aio.insecure_channel(network.grpc_exchange_endpoint) as channel:
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)
            subacc_balance = await accounts_exchange_rpc.SubaccountBalanceEndpoint(accounts_rpc_pb.SubaccountBalanceRequest(subaccount_id=subacc_id, denom=dnm))
            print("\n-- Subaccount Balance Update:\n", subacc_balance)
            self.on_account(subacc_balance)

    async def get_account_balance_list(self, subacc_id):
        async with grpc.aio.insecure_channel(network.grpc_exchange_endpoint) as channel:
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)
            subacc_list = await accounts_exchange_rpc.SubaccountBalancesList(accounts_rpc_pb.SubaccountBalancesListRequest(subaccount_id=subacc_id))
            print("\n-- Subaccount Balances List Update:\n", subacc_list)
            self.on_account(subacc_list)

    async def get_account_order_summary(self, subacc_id, direction=None):
        async with grpc.aio.insecure_channel(network.grpc_exchange_endpoint) as channel:
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)

            if direction:
                subacc_orders = await accounts_exchange_rpc.SubaccountOrderSummary(accounts_rpc_pb.SubaccountOrderSummaryRequest(subaccount_id=subacc_id, order_direction=direction))
            else:
                subacc_orders = await accounts_exchange_rpc.SubaccountOrderSummary(accounts_rpc_pb.SubaccountOrderSummaryRequest(subaccount_id=subacc_id))
            print("\n-- Subaccount Total Orders Update:\n", subacc_orders)

    """subscribe trades and orders"""
    async def stream_trade(self, on_trade: Callable, market_id, account_id=None, execution_side=None, direction=None, ):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            if execution_side and direction:
                stream_req = derivative_exchange_rpc_pb.StreamTradesRequest(
                    market_id=market_id, execution_side=execution_side, direction=direction, subaccount_id=account_id)
            elif execution_side:
                stream_req = derivative_exchange_rpc_pb.StreamTradesRequest(
                    market_id=market_id, execution_side=execution_side, subaccount_id=account_id)
            elif direction:
                stream_req = derivative_exchange_rpc_pb.StreamTradesRequest(
                    market_id=market_id, direction=direction, subaccount_id=account_id)
            elif account_id:
                stream_req = derivative_exchange_rpc_pb.StreamTradesRequest(
                    market_id=market_id, subaccount_id=account_id)
            else:
                stream_req = derivative_exchange_rpc_pb.StreamTradesRequest(
                    market_id=market_id)

            stream_resp = derivative_exchange_rpc.StreamTrades(stream_req)
            async for trade in stream_resp:
                # print("\n-- Trades Update:\n", trade)
                # import pdb
                # pdb.set_trace()
                trade_data = TradeData()
                trade_data.order_hash = trade.trade.order_hash
                trade_data.subaccount_id = trade.trade.subaccount_id
                trade_data.market_id = trade.trade.market_id
                trade_data.trade_execution_type = trade.trade.trade_execution_type
                trade_data.execution_price = round_to(
                    float(trade.trade.position_delta.execution_price)/1000000, self.ticker_size)
                trade_data.execution_quantity = trade.trade.position_delta.execution_quantity
                trade_data.execution_margin = round_to(
                    float(trade.trade.position_delta.execution_margin) / 1000000, self.ticker_size)
                trade_data.trade_direction = trade.trade.position_delta.trade_direction
                trade_data.executed_time = trade.trade.executed_at
                on_trade(trade_data)

    async def stream_order(self, market_id, account_id=None, side=None):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            if side and account_id:
                stream_req = derivative_exchange_rpc_pb.StreamOrdersRequest(
                    market_id=market_id, order_side=side, subaccount_id=account_id)
            elif side:
                stream_req = derivative_exchange_rpc_pb.StreamOrdersRequest(
                    market_id=market_id, order_side=side)
            elif account_id:
                stream_req = derivative_exchange_rpc_pb.StreamOrdersRequest(
                    market_id=market_id, subaccount_id=account_id)
            else:
                stream_req = derivative_exchange_rpc_pb.StreamOrdersRequest(
                    market_id=market_id)
            stream_resp = derivative_exchange_rpc.StreamOrders(stream_req)
            async for order in stream_resp:
                order_data = OrderData()
                order_data.order_hash = order.order.order_hash
                order_data.order_side = order.order.order_side
                order_data.market_id = order.order.market_id
                order_data.subaccount_id = order.order.subaccount_id
                order_data.margin = round_to(
                    float(order.order.margin) / 1000000, self.ticker_size)
                order_data.price = round_to(
                    float(order.order.price) / 1000000, self.ticker_size)
                order_data.quantity = float(order.order.quantity)
                order_data.unfilled_quantity = float(
                    order.order.unfilled_quantity)
                order_data.state = order.order.state
                order_data.created_time = order.order.created_at
                order_data.leverage = order_data.price * \
                    order_data.quantity / order_data.margin
                self.on_order(order_data)

    async def stream_position(self, market_id, account_id):
        async with grpc.aio.insecure_channel(self.network.grpc_exchange_endpoint) as channel:
            derivative_exchange_rpc = derivative_exchange_rpc_grpc.InjectiveDerivativeExchangeRPCStub(
                channel)
            stream_req = derivative_exchange_rpc_pb.StreamPositionsRequest(
                market_id=market_id, subaccount_id=account_id)
            stream_resp = derivative_exchange_rpc.StreamPositions(stream_req)
            async for position in stream_resp:
                print("\n-- Positions Update:\n", position)
                # import pdb
                # pdb.set_trace()
                position_data = PositionData()
                position_data.ticker = position.position.ticker
                position_data.market_id = position.position.market_id
                position_data.subaccount_id = position.position.subaccount_id
                position_data.direction = position.position.direction
                position_data.quantity = float(position.position.quantity)
                position_data.mark_price = round_to(
                    float(position.position.mark_price) / 1000000, self.ticker_size)

                if position.position.entry_price == '':
                    position_data.entry_price = 0
                else:
                    position_data.entry_price = round_to(
                        float(position.position.entry_price) / 1000000, self.ticker_size)

                if position.position.margin != '':
                    position_data.margin = round_to(
                        float(position.position.margin) / 1000000, self.ticker_size)

                if position.position.liquidation_price != '':
                    position_data.liquidation_price = round_to(
                        float(position.position.liquidation_price) / 1000000, self.ticker_size)

                position_data.aggregate_reduce_only_quantity = float(
                    position.position.aggregate_reduce_only_quantity)
                position_data.timestamp = position.timestamp
                self.on_position(position_data)

    async def stream_subaccount_balance(self, account_id):
        async with grpc.aio.insecure_channel(network.grpc_exchange_endpoint) as channel:
            accounts_exchange_rpc = accounts_rpc_grpc.InjectiveAccountsRPCStub(
                channel)
            stream_req = accounts_rpc_pb.StreamSubaccountBalanceRequest(
                subaccount_id=account_id)
            stream_resp = accounts_exchange_rpc.StreamSubaccountBalance(
                stream_req)
            async for subacc in stream_resp:
                print("\n-- Subaccount Balance Update:\n", subacc)
                import pdb
                pdb.set_trace()
                self.on_account(subacc)

    def on_account(self, accountData):
        pass

    def on_trade(self, trade_data):
        pass

    def on_order(self, order_data):
        pass

    def on_tick(self, tick_data):
        pass

    def on_timer(self):
        pass

    def on_position(self, position_data):
        pass