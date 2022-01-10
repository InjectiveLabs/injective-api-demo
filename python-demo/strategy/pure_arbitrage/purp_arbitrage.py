from perp_template import PerpTemplate
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from core.object import OrderData, PositionData, TradeData, TickData
from math import fabs
import time
from util.decimal_utils import floor_to, ceil_to
from util.constant import ORDERTYPE_DICT
from pyinjective.composer import Composer as ProtoMsgComposer
from pyinjective.transaction import Transaction
from pyinjective.client import Client
from util.constant import *
from binance.enums import *
import traceback
from binance import AsyncClient, BinanceSocketManager


class Demo(PerpTemplate):
    def __init__(self, setting, logger, mainnet_configs, testnet_configs):
        super().__init__(setting, logger, mainnet_configs, testnet_configs)
        self.setting = setting
        self.is_trading = False
        self.init_strategy()

    def init_strategy(self):
        self.ap1 = self.bp1 = self.binance_ap1 = self.binance_bp1 = -1
        self.av1 = self.bv1 = -1
        self.net_position = 0
        self.curr_duration_volume = 0
        self.last_duration_volume = 0
        self.tick = None

        self.arb_threshold = self.setting["arb_threshold"]
        self.interval = int(self.setting["interval"])
        self.binance_api_key = self.setting["binance_api_key"]
        self.binance_api_secret = self.setting["binance_api_secret"]
        self.active_orders = {}  # [order_hash, : order_data]

        self.quote_denom = denom_dict[self.quote_asset]

        self.order_size = float(self.setting["order_size"])

        self.gas_price = 500000000
        self.strategy_name = self.setting["strategy_name"]
        if self.setting.get("start_time", None):
            self.start_time = datetime.strptime(self.setting["start_time"])
        else:
            self.start_time = datetime.utcnow()
            self.setting["start_time"] = self.start_time.strftime(
                "%Y-%m-%d %H:%M%S.%f")

        self.add_schedule()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.get_init_position())
        loop.run_until_complete(
            self.get_open_orders(self.acc_id, self.market_id))
        loop.run_until_complete(self.get_orderbook())
        self.msg_list = []

        self.subscribe_stream()
        self.logger.debug("finish init")

    def add_schedule(self):
        self.sched = AsyncIOScheduler()
        self.sched.add_job(self.on_timer, 'interval',
                           seconds=self.interval)
        self.sched.add_job(self.re_balance, 'interval', seconds=3600 * self.setting['re_balance_hour'])

    def subscribe_stream(self):
        self.tasks = [
            asyncio.Task(self.stream_order(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_trade(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_position(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_orderbook(self.market_id)),
            asyncio.Task(self.subscribe_binance_orderbook())
        ]

    async def subscribe_binance_orderbook(self):
        binance_client = await AsyncClient.create()
        bm = BinanceSocketManager(binance_client)
        stream = bm.symbol_ticker_socket(symbol=self.symbol)
        async with stream as ticker_stream:
            while True:
                res = await ticker_stream.recv()
                # {
                # “u”:400900217, // order book updateId
                # “s”:”BNBUSDT”, // symbol
                # “b”:”25.35190000”, // best bid price
                # “B”:”31.21000000”, // best bid qty
                # “a”:”25.36520000”, // best ask price
                # “A”:”40.66000000” // best ask qty
                # }
                self.binance_bp1 = float(res["b"])
                self.binance_ap1 = float(res["a"])

    def start(self):
        loop = asyncio.get_event_loop()
        self.sched.start()
        self.is_trading = True
        self.logger.info("start...")
        loop.run_until_complete(asyncio.gather(*self.tasks))

    async def get_init_position(self):
        position = await self.get_position()
        if len(position.positions) > 0:
            position_data = position.positions[0]
            self.net_position = float(
                position_data.quantity) if position_data.direction == "long" else -float(position_data.quantity)
            self.logger.info(
                f"net position in {self.symbol}:{self.net_position}")
        else:
            self.logger.info("net position is zero")
            self.net_position = 0

    async def on_tick(self, tick_data: TickData):
        self.tick = tick_data
        self.ap1 = tick_data.ask_price_1
        self.bp1 = tick_data.bid_price_1
        self.av1 = tick_data.ask_volume_1
        self.bv1 = tick_data.bid_volume_1

    async def on_timer(self):
        if not self.tick:
            self.logger.critical("self.tick is None")
            return
        if self.ap1 >0 and self.bp1 > 0 and self.binance_ap1 > 0 and self.binance_bp1 > 0:
            self.logger.critical("fail to get latest orderbook price")
            return

        await self.get_address()
        self.msg_list = []

        if self.is_trading:
            if self.binance_bp1 > self.ap1 * (1 + self.arb_threshold):
                # binance bid price > injective ask price
                order_size = min(self.order_size, self.av1)
                sell_price = self.binance_bp1
                buy_price = self.ap1
                (sium_res, success) = await self.inj_limit_buy(buy_price, order_size)
                if success:
                    await self.binance_limit_sell(sell_price, order_size)
                    
            elif self.binance_ap1 < self.bp1 * (1 - self.arb_threshold):
                # binance ask price < injective bid price
                order_size = min(self.order_size, self.bv1)
                buy_price = self.binance_ap1
                sell_price = self.bp1
                (sium_res, success) = await self.inj_limit_sell(sell_price, order_size)
                if success:
                    await self.binance_limit_buy(buy_price, order_size)
                    
    async def binance_limit_buy(self, price, order_size):
        client = await AsyncClient.create(self.binance_api_key, self.binance_api_secret)
        await client.futures_create_order(symbol=self.symbol,
                                            side=SIDE_BUY,
                                            type=ORDER_TYPE_LIMIT,
                                            timeInForce=TIME_IN_FORCE_GTC,
                                            quantity=floor_to(order_size, self.step_size),
                                            price=price
                                            )
        
    async def binance_limit_sell(self, price, order_size):
        client = await AsyncClient.create(self.binance_api_key, self.binance_api_secret)
        await client.futures_create_order(symbol=self.symbol,
                                            side=SIDE_SELL,
                                            type=ORDER_TYPE_LIMIT,
                                            timeInForce=TIME_IN_FORCE_GTC,
                                            quantity=floor_to(order_size, self.step_size),
                                            price=price
                                            )
        
    async def inj_limit_buy(self, price, order_size):
        self.msg_list.append(
            self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=ceil_to(price * (1+ 0.00001), self.tick_size),
                quantity=floor_to(order_size, self.step_size),
                leverage=1,
                is_buy=True
            ))

        self.logger.info(
            "long {} {} @price{} on injecxtive exchange".format(self.order_size, self.base_asset, price))
        (sim_res, success) = await self.send_tx()
        return (sim_res, success)
    
    async def inj_limit_sell(self, price, order_size):
        self.msg_list.append(
            self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=floor_to(price * (1- 0.00001), self.tick_size),
                quantity=floor_to(order_size, self.step_size),
                leverage=1,
                is_buy=False
            ))

        self.logger.info(
            "short {} {} @price{} on injecxtive exchange".format(self.order_size, self.base_asset, price))
        (sim_res, success) = await self.send_tx()
        return (sim_res, success)
    
    async def sned_tx(self):
        tx = (
                Transaction()
                .with_messages(* self.msg_list)
                .with_sequence(self.address.get_sequence())
                .with_account_num(self.address.get_number())
                .with_chain_id(self.network.chain_id)
            )
        sim_sign_doc = tx.get_sign_doc(self.pub_key)
        sim_sig = self.priv_key.sign(sim_sign_doc.SerializeToString())
        sim_tx_raw_bytes = tx.get_tx_data(sim_sig, self.pub_key)

        # simulate tx
        (sim_res, success) = await self.client.simulate_tx(sim_tx_raw_bytes)
        if not success:
            self.logger.warning(
                "simulation failed, simulation response:{}".format(sim_res))
            return
        sim_res_msg = ProtoMsgComposer.MsgResponses(
            sim_res.result.data, simulation=True)
        self.logger.info(
            "simluation passed, simulation msg response {}".format(sim_res_msg))

        # build tx
        gas_limit = sim_res.gas_info.gas_used + \
            15000  # add 15k for gas, fee computation
        fee = [self.composer.Coin(
            amount=self.gas_price * gas_limit,
            denom=self.network.fee_denom,
        )]
        block = await self.client.get_latest_block()
        current_height = block.block.header.height
        tx = tx.with_gas(gas_limit).with_fee(fee).with_memo(
            "").with_timeout_height(current_height+50)
        sign_doc = tx.get_sign_doc(self.pub_key)
        sig = self.priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self.pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self.client.send_tx_async_mode(tx_raw_bytes)
        
        return (sim_res, success)
        

    async def on_order(self, order_data: OrderData):
        if order_data.state == "booked":
            self.active_orders[order_data.order_hash] = order_data

        if fabs(order_data.unfilled_quantity) < 1e-7 or order_data.state == "filled" or order_data.state == "canceled":
            try:
                self.active_orders.pop(order_data.order_hash)
            except Exception as e:
                self.logger.error(
                    "unexcepted order hash, can't pop it from active orders. {}".format(e))
                self.logger.error(traceback.format_exc())

    async def on_account(self, account_data):
        pass

    async def on_trade(self, trade_data):
        pass

    async def on_position(self, position_data: PositionData):
        self.net_position = position_data.quantity if position_data.direction == "long" else - \
            position_data.quantity

    def cancel_all(self):
        for order_hash in self.active_orders.keys():
            self.msg_list.append(
                self.composer.MsgCancelDerivativeOrder(
                    sender=self.sender,
                    market_id=self.market_id,
                    subaccount_id=self.acc_id,
                    order_hash=order_hash
                ))

    def inventory_management(self):
        pass

    def cancel_order(self):
        pass

    
    async def re_balance(self):
        if self.net_position > 0:
            await self.inj_limit_sell((self.ap1 + self.bp1)/2, self.net_position)
            await self.binance_limit_buy((self.binance_ap1 + self.binance_bp1)/2, self.net_position)
        elif self.net_position < 0:
            await self.inj_limit_buy((self.ap1 + self.bp1)/2, -self.net_position)
            await self.binance_limit_sell((self.binance_ap1 + self.binance_bp1)/2, -self.net_position)