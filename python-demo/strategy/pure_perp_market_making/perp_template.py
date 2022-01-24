import asyncio

from pyinjective.constant import Network
from pyinjective.composer import Composer as ProtoMsgComposer

from core.object import TickData, OrderData, TradeData, PositionData
from util.decimal_utils import floor_to, round_to
from pyinjective.wallet import PrivateKey, PublicKey, Address
from pyinjective.async_client import AsyncClient
from datetime import datetime


class PerpTemplate(object):
    def __init__(self, setting, logger, mainnet_configs, testnet_configs):
        self.logger = logger
        self.symbol = setting["symbol"]
        self.base_asset = setting["base_asset"]
        self.quote_asset = setting["quote_asset"]
        pair = self.base_asset + "/" + self.quote_asset

        if setting["is_mainnet"] == 'true':
            self.logger.info('you are using mainnet')
            self.network = Network.mainnet()
            denom_config = mainnet_configs
        else:
            self.logger.info("you are using testnet")
            self.network = Network.testnet()
            denom_config = testnet_configs
        for market_id in denom_config.sections():
            description = denom_config[market_id].get('description')

            if description:
                information = description.replace("'", "").split(" ")
                market_type = information[1]
                symbol = information[2]
                if market_type == "Derivative" and symbol == pair:
                    # Note: market_id of same traidng pair for testnet and mainnet are different.
                    # see more details from source code in injective-py
                    self.market_id = market_id
                    self.description = description
                    self.base_decimal = int(
                        denom_config[self.market_id]['base'])
                    self.quote_decimal = int(
                        denom_config[self.market_id]['quote'])
                    self.tick_size = denom_config[
                        self.market_id]['min_display_price_tick_size']
                    self.step_size = denom_config[
                        self.market_id]['min_display_quantity_tick_size']
                    self.logger.info(
                        "find metedata of trading pair {}".format(self.description))
                    self.logger.info("market id:{}".format(self.market_id))
                    break

        self.priv_key = PrivateKey.from_hex(setting["priv_key"])
        self.pub_key = self.priv_key.to_public_key()
        self.client = AsyncClient(self.network, insecure=True)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.get_address())
        self.acc_id = self.address.get_subaccount_id(index=0)
        # ATTENTION: if you use api to trade, make sure the fee_recipient is your own addres,
        # otherwise, you may not get the gas fee discount from api side.
        self.sender = self.fee_recipient = self.address.to_acc_bech32()

        self.composer = ProtoMsgComposer(network=self.network.string())
        self.is_trading = False
        self.active_orders = {}  # [order_hash: order_data]
        self.tick = None

    async def test_connect(self):
        self.get_market()

    async def get_address(self):
        self.address = await self.pub_key.to_address().async_init_num_seq(self.network.lcd_endpoint)

    """ perp market relationed function"""
    async def get_market(self):
        market_response = await self.client.get_derivative_market(
            market_id=self.market_id)
        self.logger.debug(market_response)

    async def stream_market(self):
        markets = await self.client.stream_derivative_markets()
        async for market in markets:
            self.logger.debug(market)

    """perp position related function"""
    async def get_position(self):
        positions = await self.client.get_derivative_positions(
            market_id=self.market_id, subaccount_id=self.acc_id)
        return positions

    async def get_liquidable_position(self):
        liquidable_positions = await self.client.get_derivative_liquidable_positions(
            market_id=self.market_id)
        self.logger.debug(liquidable_positions)

    """perp order related function"""
    async def get_open_orders(self, subacc_id, market_id):
        orders = await self.client.get_derivative_subaccount_orders(
            subaccount_id=subacc_id, market_id=market_id)
        await self.on_open_orders(orders)

    async def get_orders(self, market_id, order_side, subaccount_id):
        orders = await self.client.get_derivative_orders(
            market_id=market_id, order_side=order_side, subaccount_id=subaccount_id)
        self.logger.debug(orders)
        return orders

    async def get_orderbook(self):
        orderbook = await self.client.get_derivative_orderbook(market_id=self.market_id)
        print("\n-- Orderbook Update:\n", orderbook)
        tick_data = TickData()
        for i in range(min([len(orderbook.orderbook.sells),
                            len(orderbook.orderbook.buys), 5])):
            tick_data.__setattr__(
                "ask_price_" + str(i + 1),
                float(orderbook.orderbook.sells[i].price) * pow(10, self.base_decimal - self.quote_decimal))
            tick_data.__setattr__(
                "bid_price_" + str(i + 1),
                float(orderbook.orderbook.buys[i].price) * pow(10, self.base_decimal - self.quote_decimal))
            tick_data.__setattr__(
                "ask_volume_" + str(i + 1),
                float(
                    orderbook.orderbook.sells[i].quantity) * pow(10, -1 * self.base_decimal))
            tick_data.__setattr__(
                "bid_volume_" + str(i + 1),
                float(orderbook.orderbook.buys[i].quantity) * pow(10, -1 * self.base_decimal))
        await self.on_tick(tick_data)

    async def stream_orderbook(self, market_id):
        orderbooks = await self.client.stream_derivative_orderbook(market_id=market_id)
        async for orderbook in orderbooks:
            tick_data = TickData()
            for i in range(min([len(orderbook.orderbook.sells),
                                len(orderbook.orderbook.buys), 5])):
                tick_data.__setattr__(
                    "ask_price_" + str(i + 1),
                    float(orderbook.orderbook.sells[i].price) * pow(10, self.base_decimal - self.quote_decimal))
                tick_data.__setattr__(
                    "bid_price_" + str(i + 1),
                    float(orderbook.orderbook.buys[i].price) * pow(10, self.base_decimal - self.quote_decimal))
                tick_data.__setattr__(
                    "ask_volume_" + str(i + 1),
                    float(
                        orderbook.orderbook.sells[i].quantity) * pow(10, -1 * self.base_decimal))
                tick_data.__setattr__(
                    "bid_volume_" + str(i + 1),
                    float(orderbook.orderbook.buys[i].quantity) * pow(10, -1 * self.base_decimal))
            tick_data.timestamp = orderbook.timestamp
            await self.on_tick(tick_data)

    """ account related function"""
    async def get_account_order(self):
        subacc_order_summary = await self.client.get_subaccount_order_summary(
            subaccount_id=self.acc_id)
        self.logger.debug(subacc_order_summary)

    async def get_account_balance(self, subacc_id, denom='inj'):
        balance = await self.client.get_subaccount_balance(
            subaccount_id=subacc_id, denom=denom)
        self.logger.debug(balance)
        await self.on_account_balance(balance)

    async def get_account_balance_list(self, subacc_id):
        subacc_balances_list = await self.client.get_subaccount_balances_list(
            subacc_id)
        self.logger.debug(subacc_balances_list)
        self.on_account(subacc_balances_list)

    async def get_account_order_summary(self, subacc_id, direction=None):
        subacc_order_summary = await self.client.get_subaccount_order_summary(
            subaccount_id=subacc_id, market_id=self.market_id)
        self.logger.debug(subacc_order_summary)

    """subscribe trades and orders"""
    async def stream_trade(self, market_id, account_id=None, execution_side=None, direction=None, ):
        trades = await self.client.stream_derivative_trades(
            market_id=market_id, subaccount_id=account_id)
        async for trade in trades:
            curr_time = datetime.utcnow()
            self.logger.debug(trade)
            trade_data = TradeData()
            trade_data.curr_time = curr_time
            trade_data.order_hash = trade.trade.order_hash
            trade_data.subaccount_id = trade.trade.subaccount_id
            trade_data.market_id = trade.trade.market_id
            trade_data.trade_execution_type = trade.trade.trade_execution_type
            trade_data.execution_price = round_to(
                float(trade.trade.position_delta.execution_price) * pow(10, self.base_decimal - self.quote_decimal), self.tick_size)
            trade_data.execution_quantity = round_to(float(
                trade.trade.position_delta.execution_quantity) * pow(10, -1 * self.base_decimal), self.step_size)
            trade_data.execution_margin = float(
                trade.trade.position_delta.execution_margin) * pow(10, -1 * self.base_decimal)
            trade_data.trade_direction = trade.trade.position_delta.trade_direction
            trade_data.executed_time = trade.trade.executed_at
            await self.on_trade(trade_data)

    async def stream_order(self, market_id, account_id=None, side=None):
        orders = await self.client.stream_derivative_orders(
            market_id=market_id,  subaccount_id=account_id)
        async for order in orders:
            self.logger.debug(order)
            order_data = OrderData()
            order_data.order_hash = order.order.order_hash
            order_data.order_side = order.order.order_side
            order_data.market_id = order.order.market_id
            order_data.subaccount_id = order.order.subaccount_id
            order_data.margin = float(
                order.order.margin) * pow(10, self.base_decimal - self.quote_decimal)
            order_data.price = round_to(
                float(order.order.price) * pow(10, self.base_decimal - self.quote_decimal), self.tick_size)
            order_data.quantity = float(
                order.order.quantity) * pow(10, -1 * self.base_decimal)
            order_data.unfilled_quantity = float(
                order.order.unfilled_quantity) * pow(10, -1 * self.base_decimal)
            order_data.state = order.order.state
            order_data.created_time = order.order.created_at
            # for reduce-only order, margin is 0
            if order_data.margin != 0:
                order_data.leverage = order_data.price * \
                    order_data.quantity / order_data.margin
            await self.on_order(order_data)

    async def stream_position(self, market_id, account_id):
        positions = await self.client.stream_derivative_positions(market_id=market_id,
                                                                  subaccount_id=account_id)
        async for position in positions:
            self.logger.debug(position)
            position_data = PositionData()
            position_data.ticker = position.position.ticker
            position_data.market_id = position.position.market_id
            position_data.subaccount_id = position.position.subaccount_id
            position_data.direction = position.position.direction
            position_data.quantity = float(
                position.position.quantity) * pow(10, -1 * self.base_decimal)
            position_data.mark_price = round_to(
                float(position.position.mark_price) *
                pow(10, self.base_decimal - self.quote_decimal), self.tick_size)

            if position.position.entry_price == '':
                position_data.entry_price = 0
            else:
                position_data.entry_price = round_to(
                    float(position.position.entry_price) *
                    pow(10, self.base_decimal - self.quote_decimal), self.tick_size)

            if position.position.margin != '':
                position_data.margin = float(
                    position.position.margin) * self.base_decimal - self.quote_decimal

            if position.position.liquidation_price != '':
                position_data.liquidation_price = round_to(
                    float(position.position.liquidation_price) *
                    pow(10, self.base_decimal - self.quote_decimal), self.tick_size)

            position_data.aggregate_reduce_only_quantity = float(
                position.position.aggregate_reduce_only_quantity) * \
                pow(10, -1 * self.base_decimal)
            position_data.timestamp = position.timestamp
            await self.on_position(position_data)

    async def stream_subaccount_balance(self, account_id):
        subaccount = await self.client.stream_subaccount_balance(account_id)
        async for balance in subaccount:
            await self.on_account_balance(balance)

    async def on_account(self, accountData):
        pass

    async def on_trade(self, trade_data):
        pass

    async def on_order(self, order_data):
        pass

    async def on_tick(self, tick_data):
        pass

    async def on_timer(self):
        pass

    async def on_position(self, position_data):
        pass

    async def on_account_balance(self, account_balance):
        pass

    async def on_open_orders(self, open_order_list):
        # import pdb
        # pdb.set_trace()
        self.active_orders = {}
        for order in open_order_list.orders:
            order_data = OrderData()
            order_data.order_hash = order.order_hash
            order_data.order_side = order.order_side
            order_data.market_id = order.market_id
            order_data.subaccount_id = order.subaccount_id
            order_data.margin = round_to(float(order.margin) *
                                         pow(10, -1 * self.base_decimal), self.step_size)
            order_data.price = round_to(float(order.price) *
                                        pow(10, self.base_decimal - self.quote_decimal), self.tick_size)
            order_data.quantity = float(
                order.quantity) * pow(10, -1 * self.base_decimal)
            order_data.unfilled_quantity = float(
                order.unfilled_quantity) * pow(10, -1 * self.base_decimal)
            order_data.state = order.state
            order_data.created_time = order.created_at
            if order_data.margin != 0 and order_data.quantity != 0:
                order_data.leverage = order_data.price * \
                    order_data.quantity / order_data.margin
            self.active_orders[order_data.order_hash] = order_data
