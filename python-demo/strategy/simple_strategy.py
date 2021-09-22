
from strategy.template import PerpMarketManipulation
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from core.object import OrderData, PositionData, TradeData, TickData
from math import fabs
from math import log
import time
# from core.bar_generater import BarGenerater
# from core.array_manager import ArrayManager
from util.decimal_utils import floor_to
from util.constant import ORDERTYPE_DICT
from pyinjective.composer import Composer as ProtoMsgComposer
from pyinjective.transaction import Transaction
from pyinjective.client import Client
# import redis


class Demo(PerpMarketManipulation):
    def __init__(self, setting):
        super().__init__(setting)
        self.setting = setting
        self.is_trading = False
        self.init_strategy()
        self.start()

    def init_strategy(self):

        self.maker_fee = 0.001
        self.taker_fee = 0.002
        self.minimal_profit = 0.0001

        self.interval = self.setting["interval"]
        self.active_orders = {}  # [[order_hash, direction]: order_data]
        self.base_asset = "BTC"
        self.quote_asset = "USDT"
        self.tick_size = 0.001
        self.net_position = 0
        self.curr_duration_volume = 0
        self.last_duration_volume = 0

        # every 2 hour, tend to maintain net position to zero.
        self.trading_cycle = 7200
        self.clock = 0

        self.leverage = float(self.setting["leverage"])
        self.order_size = self.setting["order_size"]
        self.spread_ratio = float(self.setting["spread_ratio"])

        self.gas_price = 500000000
        self.gas_limit = 200000
        self.fee = [ProtoMsgComposer.Coin(
            amount=str(self.gas_price * self.gas_limit),
            denom=self.network.fee_denom,
        )]
        self.strategy_name = self.setting["strategy_name"]
        if self.setting.get("start_time", None):
            self.start_time = datetime.strptime(self.setting["start_time"])
        else:
            self.start_time = datetime.utcnow()
            self.setting["start_time"] = self.start_time.strftime(
                "%Y-%m-%d %H:%M%S.%f")

        self.sched = AsyncIOScheduler()
        self.sched.add_job(self.on_timer, 'interval',
                           seconds=self.interval)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.get_init_position())
        self.tick = None

        self.subscribe_stream()
        print("finish init")

    def subscribe_stream(self):
        self.tasks = [
            asyncio.Task(self.stream_order(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_trade(
                self.on_trade, self.market_id, self.acc_id)),
            asyncio.Task(self.stream_trade(
                self.on_market_trade, self.market_id)),
            asyncio.Task(self.stream_position(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_orderbook(self.market_id)),
        ]

    async def get_init_position(self):
        position = await self.get_position()
        if len(position.positions) > 0:
            position_data = position.positions[0].positions
            self.net_position = position_data.quantity if position.positions[
                0].position.direction == "long" else -position_data.quantity
            print(f"net position{self.net_position}")
        else:
            print("net position is zero")
            self.net_position = 0

    def on_tick(self, tick_data: TickData):
        self.tick = tick_data
        self.bar_generater.update_tick(self.tick)

    def on_bar(self, bar_data):
        self.array_manager.update_bar(bar_data)

    def start(self):
        self.next_duration_end_timestamp = datetime.utcnow().timestamp() + \
            self.liquitity_duration
        loop = asyncio.get_event_loop()
        self.sched.start()
        self.is_trading = True
        print("start...")
        loop.run_until_complete(asyncio.gather(*self.tasks))

    def on_market_trade(self, trade_data: TradeData):
        if self.next_duration_end_timestamp - self.liquitity_duration < trade_data.executed_time < self.next_duration_end_timestamp:
            self.curr_duration_volume += trade_data.execution_quantity
        else:
            self.next_duration_end_timestamp = datetime.utcnow().timestamp() + \
                self.liquitity_duration
            self.last_duration_volume = self.curr_duration_volume
            self.curr_duration_volume = 0

    async def on_timer(self):
        if not self.tick:
            return

        self.clock += self.interval
        if self.clock > self.trading_cycle:
            self.clock = 0
        self.acc_num, self.acc_seq = await self.address.get_num_seq(self.network.lcd_endpoint)

        if self.is_trading:
            await self.market_making()

    def cal_signal(self):
        mid_price = (self.tick.bid_price_1 + self.tick.ask_price_1) / 2
        
        half_spread = mid_price * self.spread_ratio / 2
        self.bid_price = mid_price - half_spread
        self.ask_price = mid_price + half_spread

    async def market_making(self):
        self.cal_signal()
        self.cancel_all()
        self.quote_bid_ask()
        # send tx, including canceling, bid and ask.
        if len(self.msg_list):
            tx = (
                Transaction()
                .with_messages(* self.msg_list)
                .with_sequence(self.acc_seq)
                .with_account_num(self.acc_num)
                .with_chain_id(self.network.chain_id)
                .with_gas(self.gas_limit)
                .with_fee(self.fee)
                .with_memo("")
                .with_timeout_height(0)
            )

            # build signed tx
            sign_doc = tx.get_sign_doc(self.pub_key)
            sig = self.priv_key.sign(sign_doc.SerializeToString())
            tx_raw_bytes = tx.get_tx_data(sig, self.pub_key)
            client = Client(self.network.grpc_endpoint, insecure=True)
            # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
            res = client.send_tx_sync_mode(tx_raw_bytes)
            print(res)

    def on_order(self, order_data: OrderData):
        pass
    
    def on_account(self, account_data):
        pass

    def on_trade(self, trade_data):
        pass

    def on_position(self, position_data: PositionData):
        self.net_position = position_data.quantity if position_data.direction == "long" else - \
            position_data.quantity

    def quote_bid_ask(self):
        self.msg_list.append(ProtoMsgComposer.MsgCreateDerivativeLimitOrder(
            market_id=self.market_id,
            sender=self.sender,
            subaccount_id=self.acc_id,
            fee_recipient=self.fee_recipient,
            price=floor_to(self.bid_price, self.tick_size),
            quantity=self.order_size,
            leverage=self.leverage,
            isBuy=True
        ))

        print("long {}btc @price{}".format(self.order_size, self.bid_price))

        self.msg_list.append(ProtoMsgComposer.MsgCreateDerivativeLimitOrder(
            market_id=self.market_id,
            sender=self.sender,
            subaccount_id=self.acc_id,
            fee_recipient=self.fee_recipient,
            price=floor_to(self.ask_price, self.tick_size),
            quantity=self.order_size,
            leverage=self.leverage,
            isBuy=False
        ))
        print("short {}btc @price{}".format(self.order_size, self.ask_price))

        # return [buy_msg, sell_msg]

    def inventory_management(self):
        pass

    def cancel_order(self):
        pass

    def cancel_all(self):
        for order_hash in self.active_orders.keys():
            self.msg_list.append(ProtoMsgComposer.MsgCancelDerivativeOrder(
                sender=self.sender,
                market_id=self.market_id,
                subaccount_id=self.acc_id,
                order_hash=order_hash
            ))
