from perp_template import PerpTemplate
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from core.object import OrderData, PositionData, TradeData, TickData
from math import fabs
from util.decimal_utils import floor_to, ceil_to
from pyinjective.composer import Composer as ProtoMsgComposer
from pyinjective.transaction import Transaction
from pyinjective.client import Client
from binance.enums import *
import traceback
from binance import AsyncClient, BinanceSocketManager
import time

class Demo(PerpTemplate):
    def __init__(self, setting, logger, mainnet_configs, testnet_configs):
        super().__init__(setting, logger, mainnet_configs, testnet_configs)
        self.setting = setting
        self.is_trading = False
        self.init_strategy()

    def init_strategy(self):
        self.ap1 = self.bp1 = self.binance_ap1 = self.binance_bp1 = -1
        self.av1 = self.bv1 = -1
        self.curr_duration_volume = 0
        self.last_duration_volume = 0
        self.tick = None

        self.inj_funding_rate = 0.0
        self.binance_funding_rate = 0.0
        self.net_position = 0
        self.net_position_binance = 0

        self.arb_threshold = float(self.setting["arb_threshold"])
        self.interval = int(self.setting["interval"])
        self.binance_api_key = self.setting["binance_api_key"]
        self.binance_api_secret = self.setting["binance_api_secret"]
        self.active_orders = {}  # [order_hash, : order_data]

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

    def subscribe_stream(self):
        self.tasks = [
            asyncio.Task(self.stream_order(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_trade(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_position(self.market_id, self.acc_id)),
            asyncio.Task(self.stream_orderbook(self.market_id)),
            asyncio.Task(self.subscribe_binance_orderbook()),
            asyncio.Task(self.subscribe_inj_exchange_funding()),
            asyncio.Task(self.subscribe_binance_exchange_funding()),
            asyncio.Task(self.subscribe_binance_position())
        ]

    async def subscribe_inj_exchange_funding(self):
        markets = await self.client.stream_derivative_markets()
        async for market in markets:
            # print(market)
            if market.market.market_id == self.market_id:
                hourly_interest_rate = float(
                    market.market.perpetual_market_info.hourly_interest_rate)
                funding_cap = float(market.market.perpetual_market_info.hourly_funding_rate_cap)
                cumulative_price = float(market.market.perpetual_market_funding.cumulative_price)
                divisor = (time.time() % 3600 )* 24
                twap_est = cumulative_price / divisor
                self.inj_funding_rate = max(min(hourly_interest_rate + twap_est, funding_cap), -funding_cap)
                
                # Only execute in the last 30 mins
                if time.time() % 3600 > 1800:
                    await self.on_funding_rates()

    async def subscribe_binance_exchange_funding(self):
        binance_client = await AsyncClient.create()
        bm = BinanceSocketManager(binance_client)
        # <symbol>@markPrice, binance api doc: https://binance-docs.github.io/apidocs/futures/en/#mark-price-stream
        # e.g. payload
        # {
        #     "e": "markPriceUpdate",     // Event type
        #     "E": 1562305380000,         // Event time
        #     "s": "BTCUSDT",             // Symbol
        #     "p": "11794.15000000",      // Mark price
        #     "i": "11784.62659091",      // Index price
        #     "P": "11784.25641265",      // Estimated Settle Price, only useful in the last hour before the settlement starts
        #     "r": "0.00038167",          // Funding rate
        #     "T": 1562306400000          // Next funding time
        # }
        stream = bm.multiplex_socket([self.symbol.lower() + "@markPrice"])
        async with stream as funding_stream:
            while True:
                res = await funding_stream.recv()
                self.binance_funding_rate = float(res["r"])

    async def on_funding_rates(self):
        if self.inj_funding_rate * self.binance_funding_rate < 0:
            await self.get_address()
            self.msg_list = []
            if self.inj_funding_rate > 0 and self.net_position < self.order_size:
                # Use the most closed price in inj orderbook to execute the first leg
                await self.inj_limit_buy(self.inj_ask_price_1 - self.tick_size, (self.order_size - self.net_position))
            elif self.inj_funding_rate < 0 and self.net_position > -self.order_size:
                # Use the most closed price in inj orderbook to execute the first leg
                await self.inj_limit_sell(self.inj_bid_price_1 + self.tick_size, (self.order_size - self.net_position))

    async def subscribe_binance_position(self):
        binance_client = await AsyncClient.create(self.binance_api_key, self.binance_api_secret)
        bm = BinanceSocketManager(binance_client)
        user_ts = bm.futures_user_socket()
        async with user_ts as tscm:
            while True:
                res = await tscm.recv()
                if not res:
                    continue
                if res['e'] == 'ACCOUNT_UPDATE':
                    # binance doc: https://binance-docs.github.io/apidocs/futures/en/#event-balance-and-position-update
                    asset = res['a']
                    positions = asset["P"]
                    # "P":[
                    #     {
                    #     "s":"BTCUSDT",            // Symbol
                    #     "pa":"0",                 // Position Amount
                    #     "ep":"0.00000",            // Entry Price
                    #     "cr":"200",               // (Pre-fee) Accumulated Realized
                    #     "up":"0",                     // Unrealized PnL
                    #     "mt":"isolated",              // Margin Type
                    #     "iw":"0.00000000",            // Isolated Wallet (if isolated position)
                    #     "ps":"BOTH"                   // Position Side
                    #     }，
                    #     ]
                    for position in positions:
                        if position['s'] == self.symbol:
                            self.net_position_binance = float(
                                position['pa'])
                            await self.on_binance_position()
                elif res['e'] == 'error':
                    self.logger.critical(
                        'websocket error, {}'.format(res))

    async def on_position(self, position_data: PositionData):
        self.net_position = position_data.quantity if position_data.direction == "long" else - \
            position_data.quantity

    async def on_binance_position(self):
        if self.net_position + self.net_position_binance != 0:
            if self.net_position_binance > -self.net_position:
                # Use limit order(Taker) to execute the second leg
                await self.binance_limit_sell(self.binance_bp1, abs(-self.net_position - self.net_position_binance))
            elif self.net_position_binance < -self.net_position:
                await self.binance_limit_buy(self.binance_ap1, abs(-self.net_position - self.net_position_binance))

    async def subscribe_binance_orderbook(self):
        binance_client = await AsyncClient.create()
        bm = BinanceSocketManager(binance_client)
        stream = bm.symbol_ticker_socket(symbol=self.symbol)
        async with stream as ticker_stream:
            while True:
                res = await ticker_stream.recv()
                # {
                # "u":400900217, // order book updateId
                # "s":"BNBUSDT", // symbol
                # "b":"25.35190000", // best bid price
                # "B":"31.21000000", // best bid qty
                # "a":"25.36520000", // best ask price
                # "A":"40.66000000" // best ask qty
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
        if self.ap1 > 0 and self.bp1 > 0 and self.binance_ap1 > 0 and self.binance_bp1 > 0:
            self.logger.critical("failed to get latest orderbook price")
            return

    async def binance_limit_buy(self, price, order_size):
        client = await AsyncClient.create(self.binance_api_key, self.binance_api_secret)
        await client.futures_create_order(symbol=self.symbol,
                                          side=SIDE_BUY,
                                          type=ORDER_TYPE_LIMIT,
                                          timeInForce=TIME_IN_FORCE_GTC,
                                          quantity=floor_to(
                                              order_size, self.step_size),
                                          price=price
                                          )

    async def binance_limit_sell(self, price, order_size):
        client = await AsyncClient.create(self.binance_api_key, self.binance_api_secret)
        await client.futures_create_order(symbol=self.symbol,
                                          side=SIDE_SELL,
                                          type=ORDER_TYPE_LIMIT,
                                          timeInForce=TIME_IN_FORCE_GTC,
                                          quantity=floor_to(
                                              order_size, self.step_size),
                                          price=price
                                          )

    async def inj_limit_buy(self, price, order_size):
        self.msg_list.append(
            self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=ceil_to(price * (1 + 0.00001), self.tick_size),
                quantity=floor_to(order_size, self.step_size),
                leverage=1,
                is_buy=True
            ))

        self.logger.info(
            "long {} {} @price{} on injective exchange".format(self.order_size, self.base_asset, price))
        (sim_res, success) = await self.send_tx()
        return (sim_res, success)

    async def inj_limit_sell(self, price, order_size):
        self.msg_list.append(
            self.composer.MsgCreateDerivativeLimitOrder(
                market_id=self.market_id,
                sender=self.sender,
                subaccount_id=self.acc_id,
                fee_recipient=self.fee_recipient,
                price=floor_to(price * (1 - 0.00001), self.tick_size),
                quantity=floor_to(order_size, self.step_size),
                leverage=1,
                is_buy=False
            ))

        self.logger.info(
            "short {} {} @price{} on injective exchange".format(self.order_size, self.base_asset, price))
        (sim_res, success) = await self.send_tx()
        return (sim_res, success)

    async def send_tx(self):
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
            "simulation passed, simulation msg response {}".format(sim_res_msg))

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
