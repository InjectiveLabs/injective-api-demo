from perp_template import PerpTemplate
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from core.object import OrderData, PositionData, TradeData, TickData
from math import fabs
from math import log
import time
from util.decimal_utils import floor_to
from pyinjective.composer import Composer as ProtoMsgComposer
from pyinjective.transaction import Transaction
from pyinjective.client import Client
from util.constant import *
import traceback


class Demo(PerpTemplate):
    def __init__(self, setting, logger, mainnet_configs, testnet_configs):
        super().__init__(setting, logger, mainnet_configs, testnet_configs)
        self.setting = setting
        self.is_trading = False
        self.init_strategy()

    def init_strategy(self):
        self.net_position = 0
        self.curr_duration_volume = 0
        self.last_duration_volume = 0
        self.tick = None

        self.interval = int(self.setting["interval"])
        self.re_balance_interval_hour = self.setting["re_balance_interval_hour"]
        self.active_orders = {}  # [order_hash, : order_data]

        self.quote_denom = denom_dict[self.quote_asset]

        self.leverage = float(self.setting["leverage"])
        self.order_size = float(self.setting["order_size"])
        self.spread_ratio = float(self.setting["spread_ratio"])

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
                           seconds=self.interval, id="timer")

        self.sched.add_job(self.close_position, 'interval',
                           seconds=int(self.re_balance_interval_hour) * 3600, id="re_balance_position")
    def subscribe_stream(self):
        self.tasks = [
            asyncio.Task(self.stream_order(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_trade(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_position(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_orderbook(self.market_id)),
        ]

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

    async def on_timer(self):
        if not self.tick:
            self.logger.critical("self.tick is None")
            return
        if self.tick.ask_price_1 == 0 or self.tick.bid_price_1 == 0:
            self.logger.critical("fail to get latest orderbook price")
            return

        await self.get_address()

        if self.is_trading:
            await self.market_making()

    def cal_signal(self):
        mid_price = (self.tick.bid_price_1 + self.tick.ask_price_1) / 2

        half_spread = mid_price * self.spread_ratio / 2
        self.bid_price = mid_price - half_spread
        self.ask_price = mid_price + half_spread

    async def market_making(self):
        self.msg_list = []
        self.cancel_all()
        self.cal_signal()
        self.quote_bid_ask()
        if len(self.msg_list):
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
                20000  # add 15k for gas, fee computation
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
            res = await self.client.send_tx_block_mode(tx_raw_bytes)
            res_msg = ProtoMsgComposer.MsgResponses(res.data)
            self.logger.info(
                "tx response: {}\n tx msg response:{}".format(res, res_msg))

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

    def quote_bid_ask(self):
        self.msg_list.append(
            self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=floor_to(self.bid_price, self.tick_size),
                quantity=floor_to(self.order_size, self.step_size),
                leverage=self.leverage,
                is_buy=True
            ))

        self.logger.info(
            "long {}btc @price{}".format(self.order_size, self.bid_price))

        self.msg_list.append(self.composer.MsgCreateDerivativeLimitOrder(
            market_id=self.market_id,
            sender=self.sender,
            subaccount_id=self.acc_id,
            fee_recipient=self.fee_recipient,
            price=floor_to(self.ask_price, self.tick_size),
            quantity=floor_to(self.order_size, self.step_size),
            leverage=self.leverage,
            is_buy=False
        ))
        self.logger.info(
            "short {}btc @price{}".format(self.order_size, self.ask_price))

    def cancel_all(self):
        for order_hash in self.active_orders.keys():
            self.msg_list.append(
                self.composer.MsgCancelDerivativeOrder(
                    sender=self.sender,
                    market_id=self.market_id,
                    subaccount_id=self.acc_id,
                    order_hash=order_hash
                ))

    async def close_position(self):
        self.sched.pause_job("timer")
        
        self.msg_list = []
        
        self.cancel_all()
        
        if self.net_position > 0:
            self.msg_list.append(self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=floor_to(self.tick.bid_price_1 * (1-0.0001), self.tick_size),
                quantity=floor_to(self.net_position, self.step_size),
                is_reduce_only=True,
                is_buy=False
            ))
        elif self.net_position < 0:
            self.msg_list.append(
                self.composer.MsgCreateDerivativeLimitOrder(
                    market_id=self.market_id,
                    sender=self.sender,
                    subaccount_id=self.acc_id,
                    fee_recipient=self.fee_recipient,
                    price=floor_to(self.tick.ask_price_1 * (1+ 0.0001), self.tick_size),
                    quantity=floor_to(-self.net_position, self.step_size),
                    is_reduce_only=True,
                    is_buy=True
            ))
            
        if len(self.msg_list):
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
                20000  # add 15k for gas, fee computation
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
            res = await self.client.send_tx_block_mode(tx_raw_bytes)
            res_msg = ProtoMsgComposer.MsgResponses(res.data)
            self.logger.info(
                "tx response: {}\n tx msg response:{}".format(res, res_msg))
        
        self.sched.resume_job("timer")
                
    def inventory_management(self):
        pass

    def cancel_order(self):
        pass