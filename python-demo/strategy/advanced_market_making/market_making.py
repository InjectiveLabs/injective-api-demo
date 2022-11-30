from time import time_ns, time
from datetime import datetime
from asyncio import (
    create_task,
    Event,
    sleep,
    wait,
    FIRST_EXCEPTION,
)
import logging
from pyinjective.transaction import Transaction
from pyinjective.wallet import PrivateKey
from pyinjective.utils import derivative_price_from_backend

from sortedcontainers import SortedList
from objs import (
    PositionDerivative,
    MarketDerivative,
    OrderDerivative,
    BalanceDerivative,
)
from configparser import SectionProxy
from math import log
from random import random
from typing import List, Dict, Tuple
from utilities import (
    build_client_and_composer,
    switch_network,
    round_down,
    truncate_float,
    _handle_task_result,
)
from avellaneda_stoikov import avellaneda_stoikov_model
from market_making_template import MarketMaker


class PerpMarketMaker(MarketMaker):
    def __init__(
        self,
        avellaneda_stoikov_configs: SectionProxy,
    ):

        priv_key = avellaneda_stoikov_configs["private_key"]
        nodes = avellaneda_stoikov_configs["nodes"].split(",")
        super().__init__(avellaneda_stoikov_configs)
        self.nodes = nodes
        self.is_mainnet = avellaneda_stoikov_configs.getboolean("is_mainnet", False)
        self.node_index, self.network, insecure = switch_network(
            self.nodes, 0, self.is_mainnet
        )
        self.client, self.composer = build_client_and_composer(self.network, insecure)

        # load account
        self.priv_key = PrivateKey.from_hex(priv_key)
        self.pub_key = self.priv_key.to_public_key()
        self.address = self.pub_key.to_address().init_num_seq(self.network.lcd_endpoint)
        self.subaccount_id = self.address.get_subaccount_id(index=0)
        logging.info("Subaccount ID: %s" % self.subaccount_id)

        self.fee_recipient = "inj1wrg096y69grgf8yg6tqxnh0tdwx4x47rsj8rs3"
        self.update_interval = avellaneda_stoikov_configs.getint("update_interval", 60)
        logging.info("update interval: %d" % self.update_interval)

        ############################
        self.position = PositionDerivative()
        if avellaneda_stoikov_configs.get("base") and avellaneda_stoikov_configs.get(
            "quote"
        ):
            self.market = MarketDerivative(
                base=avellaneda_stoikov_configs["base"],
                quote=avellaneda_stoikov_configs["quote"],
                network=self.network,
                is_mainnet=self.is_mainnet,
            )
        else:
            raise Exception("invalid base or quote ticker")
        self.balance = BalanceDerivative(
            available_balance=avellaneda_stoikov_configs.getfloat(
                "available_balance", 10.0
            )
        )
        self.ask_price = 0
        self.bid_price = 0

        self.n_orders = avellaneda_stoikov_configs.getint("n_orders", 5)
        logging.info("n_orders: %s" % self.n_orders)
        self.leverage = avellaneda_stoikov_configs.getfloat("leverage", 1)
        logging.info("leverage: %s" % self.leverage)

        # Avellaneda Stoikov model parameters
        self.gamma = avellaneda_stoikov_configs.getfloat("gamma", 0.7)
        self.sigma = avellaneda_stoikov_configs.getfloat("sigma", 0.7)  # market STD
        self.position_max = avellaneda_stoikov_configs.getint(
            "position_max", 10
        )  # our tolerance to the position
        self.limit_horizon = avellaneda_stoikov_configs.getboolean(
            "limit_horizon", False
        )  # is this a inifinite horizon model or finite horizon model
        self.kappa = avellaneda_stoikov_configs.getfloat(
            "kappa", 1.5
        )  # Order filling rate
        self.dt = avellaneda_stoikov_configs.getfloat("dt", 3)
        self.T = avellaneda_stoikov_configs.getint("T", 600)

        self.orders: Dict[str, SortedList] = {
            "bids": SortedList(),
            "asks": SortedList(),
            "reduce_only_orders": SortedList(),
        }

        self.tob_bid_price = 0
        self.sob_best_bid_price = 0
        self.tob_ask_price = 0
        self.sob_best_ask_price = 0

        self.last_order_delta = avellaneda_stoikov_configs.getfloat(
            "last_order_delta", 0.40
        )
        self.first_order_delta = avellaneda_stoikov_configs.getfloat(
            "first_order_delta", 0.05
        )
        logging.info(
            "first_order_delta: %s, last_order_delta: %s :"
            % (self.first_order_delta, self.last_order_delta)
        )

        self.first_asset_allocation = avellaneda_stoikov_configs.getfloat(
            "first_asset_allocation", 0
        )
        self.last_asset_allocation = avellaneda_stoikov_configs.getfloat(
            "last_asset_allocation", 0.4
        )

        self.estimated_fee_ratio = avellaneda_stoikov_configs.getfloat(
            "estimated_fee_ratio", 0.005
        )
        self.initial_margin_ratio = 1

        self.bid_total_asset_allocation = avellaneda_stoikov_configs.getfloat(
            "bid_total_asset_allocation", 0.09
        ) * (
            1 - self.estimated_fee_ratio
        )  # fraction of total asset
        logging.info("bid_total_asset_allocation: %s" % self.bid_total_asset_allocation)
        self.ask_total_asset_allocation = avellaneda_stoikov_configs.getfloat(
            "ask_total_asset_allocation", 0.11
        ) * (
            1 - self.estimated_fee_ratio
        )  # fraction of total asset
        logging.info("ask_total_asset_allocation: %s" % self.ask_total_asset_allocation)

        self.price_delta_ratio = self._compute_price_delta()
        self.tob_asset_allocation = self._compute_tob_asset_allocation()
        logging.info("tob_asset_allocation: %s", self.tob_asset_allocation)
        self.asset_deltas = self._compute_asset_delta()

        self.current_order_size = 0.0001

        self.max_bid_order_size = 0.0
        self.max_ask_order_size = 0.0
        self.last_trade_price = 0.0
        self.last_trade_ts = 0
        # in the process of replace orders
        self.price_feed = Event()
        self.replace_event = Event()
        self.margin_event = Event()

    def _compute_price_delta(self) -> float:
        price_delta = (self.last_order_delta - self.first_order_delta) / (
            self.n_orders - 1
        )
        return price_delta

    def _compute_tob_asset_allocation(self) -> Tuple[float, float]:
        logging.debug(
            f"self.balance.available_balance {self.balance.available_balance}"
        )
        bid_asset_allocation = (
            self.bid_total_asset_allocation
            * self.balance.available_balance
            * 2
            / (
                (2 + self.last_asset_allocation + self.first_asset_allocation)
                * self.n_orders
            )
        )
        ask_asset_allocation = (
            self.ask_total_asset_allocation
            * self.balance.available_balance
            * 2
            / (
                (2 + self.last_asset_allocation + self.first_asset_allocation)
                * self.n_orders
            )
        )
        return bid_asset_allocation, ask_asset_allocation

    def _compute_asset_delta(self) -> Tuple[float, float]:
        (
            bid_asset_allocation,
            ask_asset_allocation,
        ) = self._compute_tob_asset_allocation()
        bid_asset_delta = (
            (self.last_asset_allocation - self.first_asset_allocation)
            * bid_asset_allocation
            / (self.n_orders - 1)
        )

        ask_asset_delta = (
            (self.last_asset_allocation - self.first_asset_allocation)
            * ask_asset_allocation
            / (self.n_orders - 1)
        )
        return bid_asset_delta, ask_asset_delta

    def _compute_prices(self, i: int):

        bid_base = self.bid_price
        ask_base = self.ask_price
        if bid_base < ask_base:
            bid_base = self.bid_price
            ask_base = self.ask_price

        bid_price = round(
            bid_base * (1 - self.price_delta_ratio * i) - random(),
            4,
        )
        ask_price = round(
            ask_base * (1 + self.price_delta_ratio * i) + random(),
            4,
        )
        return bid_price, ask_price

    def _price_validation(
        self,
        bid_price: float,
        ask_price: float,
        bid_quantity: float,
        ask_quantity: float,
    ):
        success = True

        bid_required_margin = (
            self.oracle_price / ((self.initial_margin_ratio - 1) * bid_quantity)
            + bid_price * bid_quantity
        )
        if (
            bid_required_margin
            < self.balance.available_balance * self.bid_total_asset_allocation
        ):
            logging.warning(
                "insufficient bid required margin: %f,  balance: %f"
                % (
                    bid_required_margin,
                    self.balance.available_balance * self.bid_total_asset_allocation,
                )
            )
            bid_price = round(self.oracle_price * 0.75, 4)
            success = False

        ask_required_margin = (
            self.oracle_price * (1 + self.initial_margin_ratio) * ask_quantity
            - ask_price * ask_quantity
        )
        if (
            ask_required_margin
            > self.balance.available_balance * self.ask_total_asset_allocation
        ):
            logging.warning(
                "insufficient ask required margin: %f,  balance: %f"
                % (
                    ask_required_margin,
                    self.balance.available_balance * self.ask_total_asset_allocation,
                )
            )
            ask_price = round(self.oracle_price * 1.25, 4)
            success = False

        return success, bid_price, ask_price

    def _compute_asset_allocation(self, i: int) -> Tuple[float, float]:
        bid_asset_allocation = truncate_float(
            self.tob_asset_allocation[0] + self.asset_deltas[0] * i, 5
        )
        ask_asset_allocation = truncate_float(
            self.tob_asset_allocation[1] + self.asset_deltas[1] * i, 5
        )
        return bid_asset_allocation, ask_asset_allocation

    def _compute_order_price_quantity(
        self, i: int, bid_price: float, ask_price: float
    ) -> Tuple[float, float, float, float]:

        # bid_price, ask_price = self._compute_prices(i)
        asset_allocation = self._compute_asset_allocation(i)
        logging.debug(f"asset_allocation: {asset_allocation}")

        bid_quantity = truncate_float(asset_allocation[0] / bid_price, 4)
        ask_quantity = truncate_float(asset_allocation[1] / ask_price, 4)
        logging.debug(
            f"batch {i}, bid_price: {bid_price:.2f}, ask_price: {ask_price:.2f}, bid_asset_allocation: {asset_allocation[0]:.5f}, ask_asset_allocation: {asset_allocation[1]:.5f}, bid_quantity: {bid_quantity:.4f}, ask_quantity: {ask_quantity:.4f}"
        )

        self.current_order_size = min(ask_quantity, self.current_order_size)
        return bid_price, ask_price, bid_quantity, ask_quantity

    def _build_first_batch_orders(self):
        logging.debug("building first batch orders")

        self.orders["bids"].clear()
        self.orders["asks"].clear()
        self.orders["reduce_only_orders"].clear()

        logging.debug(
            f"first batch: bid_price {self.bid_price}, ask_price {self.ask_price}"
        )
        for i in range(self.n_orders):
            bid_price, ask_price = self._compute_prices(i)
            logging.debug(
                "batch %d, bid_price: %f, ask_price: %f" % (i, bid_price, ask_price)
            )
            (
                bid_price,
                ask_price,
                bid_quantity,
                ask_quantity,
            ) = self._compute_order_price_quantity(i, bid_price, ask_price)

            # only add reduce only order in the first batch
            if i == 0:
                self.position.residual_reduce_only_quantity = self.position.net_quantity
                if self.position.residual_reduce_only_quantity > 0:

                    if self.position.direction == "long":
                        reduce_only_quantity = round_down(
                            self.position.residual_reduce_only_quantity / 2, 4
                        )
                        if reduce_only_quantity >= 0.0001:
                            self.orders["reduce_only_orders"].add(
                                OrderDerivative(
                                    price=bid_price,
                                    quantity=bid_quantity,
                                    timestamp=time_ns(),
                                    side="sell",
                                    msg=self.composer.DerivativeOrder(
                                        market_id=self.market.market_id,
                                        fee_recipient=self.fee_recipient,
                                        subaccount_id=self.subaccount_id,
                                        price=ask_price - 0.5,
                                        quantity=reduce_only_quantity,
                                        leverage=self.leverage,
                                        is_buy=False,
                                        is_reduce_only=True,
                                    ),
                                )
                            )

                    elif self.position.direction == "short":
                        # direction == 'short'
                        reduce_only_quantity = round_down(
                            self.position.residual_reduce_only_quantity / 2, 4
                        )
                        if reduce_only_quantity >= 0.0001:
                            self.orders["reduce_only_orders"].add(
                                OrderDerivative(
                                    price=bid_price,
                                    quantity=bid_quantity,
                                    timestamp=time_ns(),
                                    side="buy",
                                    msg=self.composer.DerivativeOrder(
                                        market_id=self.market.market_id,
                                        fee_recipient=self.fee_recipient,
                                        subaccount_id=self.subaccount_id,
                                        price=bid_price + 0.5,
                                        quantity=reduce_only_quantity,
                                        leverage=self.leverage,
                                        is_buy=True,
                                        is_reduce_only=True,
                                    ),
                                )
                            )
                    else:
                        pass

            self.max_ask_order_size = max(ask_quantity, self.max_ask_order_size)
            self.max_bid_order_size = max(bid_quantity, self.max_bid_order_size)

            logging.debug(f"{self.max_bid_order_size} {self.max_ask_order_size}")

            ts = time_ns()

            bid = OrderDerivative(
                price=bid_price,
                quantity=bid_quantity,
                timestamp=ts,
                side="buy",
                msg=self.composer.DerivativeOrder(
                    market_id=self.market.market_id,
                    fee_recipient=self.fee_recipient,
                    subaccount_id=self.subaccount_id,
                    price=bid_price,
                    quantity=bid_quantity,
                    leverage=self.leverage,
                    is_buy=True,
                ),
            )
            ask = OrderDerivative(
                price=ask_price,
                quantity=ask_quantity,
                timestamp=ts,
                side="sell",
                msg=self.composer.DerivativeOrder(
                    market_id=self.market.market_id,
                    fee_recipient=self.fee_recipient,
                    subaccount_id=self.subaccount_id,
                    price=ask_price,
                    quantity=ask_quantity,
                    leverage=self.leverage,
                    is_buy=False,
                ),
            )
            logging.debug(f"{bid.price, bid.quantity}, ts: {bid.timestamp}")
            logging.debug(f"#{ask.price, ask.quantity}, ts: {ask.timestamp}")
            self.orders["bids"].add(bid)
            self.orders["asks"].add(ask)

    def build_cancel_orders_by_hash_msg(self, i: int):
        if (len(self.orders["bids"]) == self.n_orders) and (
            len(self.orders["asks"]) == self.n_orders
        ):
            logging.debug(f"IF ARM: replace order one by one")
            logging.debug(f"bids order {self.orders['bids']}")
            logging.debug(f"asks order {self.orders['asks']}")
            derivative_orders_to_cancel = []

            bid_order = self.orders["bids"].pop(0)
            ask_order = self.orders["asks"].pop(0)
            if bid_order.order_hash:
                derivative_orders_to_cancel.append(
                    self.composer.OrderData(
                        market_id=self.market.market_id,
                        subaccount_id=self.subaccount_id,
                        order_hash=bid_order.order_hash,
                    )
                )
            if ask_order.order_hash:
                derivative_orders_to_cancel.append(
                    self.composer.OrderData(
                        market_id=self.market.market_id,
                        subaccount_id=self.subaccount_id,
                        order_hash=ask_order.order_hash,
                    )
                )
            logging.debug(
                f"good bid order to cancel, price: {bid_order.price:6.2f}, quantity: {bid_order.quantity:6.4f}, ts: {bid_order.timestamp}, hash: {bid_order.order_hash}"
            )
            logging.debug(
                f"good ask order to cancel, price: {ask_order.price:6.2f}, quantity: {ask_order.quantity:6.4f}, ts: {ask_order.timestamp}, hash: {ask_order.order_hash}"
            )

            if i == 0 and len(self.orders["reduce_only_orders"]) > 0:
                reduce_only_order = self.orders["reduce_only_orders"].pop(0)
                derivative_orders_to_cancel.append(
                    self.composer.OrderData(
                        market_id=self.market.market_id,
                        subaccount_id=self.subaccount_id,
                        order_hash=reduce_only_order.order_hash,
                    )
                )

                logging.debug(
                    f"good reduce only order to cancel, price: {reduce_only_order.price:6.2f}, quantity: {reduce_only_order.quantity:6.4f}, hash: {reduce_only_order.order_hash}"
                )

            logging.debug(
                "good derivative_orders_to_cancel: %s"
                % len(derivative_orders_to_cancel)
            )
        else:
            logging.debug(
                f"bid_orders {len(self.orders['bids'])}, ask_orders {len(self.orders['asks'])}, reduce_only_orders {len(self.orders['reduce_only_orders'])}"
            )
            # one of the local orders has size greater than n_orders
            derivative_orders_to_cancel = []
            if len(self.orders["bids"]) == self.n_orders:
                bid_order = self.orders["bids"].pop(0)
                derivative_orders_to_cancel.append(
                    self.composer.OrderData(
                        market_id=self.market.market_id,
                        subaccount_id=self.subaccount_id,
                        order_hash=bid_order.order_hash,
                    )
                )
                logging.debug(
                    f"bid order to cancel, price: {bid_order.price:6.2f}, quantity: {bid_order.quantity:6.4f}, hash: {bid_order.order_hash}"
                )
            else:
                while len(self.orders["bids"]) > self.n_orders - 1:
                    bid_order = self.orders["bids"].pop(0)
                    logging.info(f"bid order hash: {bid_order.order_hash}")
                    derivative_orders_to_cancel.append(
                        self.composer.OrderData(
                            market_id=self.market.market_id,
                            subaccount_id=self.subaccount_id,
                            order_hash=bid_order.order_hash,
                        )
                    )
            if len(self.orders["asks"]) == self.n_orders:
                ask_order = self.orders["asks"].pop(0)
                derivative_orders_to_cancel.append(
                    self.composer.OrderData(
                        market_id=self.market.market_id,
                        subaccount_id=self.subaccount_id,
                        order_hash=ask_order.order_hash,
                    )
                )
                logging.debug(
                    f"ask order to cancel, price: {ask_order.price:6.2f}, quantity: {ask_order.quantity:6.4f}, hash: {ask_order.order_hash}"
                )
            else:
                while len(self.orders["asks"]) > self.n_orders - 1:
                    ask_order = self.orders["asks"].pop(0)
                    logging.info(f"ask order hash: {ask_order.order_hash}")
                    derivative_orders_to_cancel.append(
                        self.composer.OrderData(
                            market_id=self.market.market_id,
                            subaccount_id=self.subaccount_id,
                            order_hash=ask_order.order_hash,
                        )
                    )
            logging.debug(
                "derivative_orders_to_cancel: %s" % len(derivative_orders_to_cancel)
            )

        if i != 0:
            return derivative_orders_to_cancel

        # redeuce only orders
        for order in self.orders["reduce_only_orders"]:
            derivative_orders_to_cancel.append(
                self.composer.OrderData(
                    market_id=self.market.market_id,
                    subaccount_id=self.subaccount_id,
                    order_hash=order.order_hash,
                )
            )
        self.orders["reduce_only_orders"].clear()
        return derivative_orders_to_cancel

    def build_place_order_by_price_msg(self, i: int):
        bid_price, ask_price = self._compute_prices(i)
        logging.debug(f"batch {i} bid_price: {bid_price}, ask_price: {ask_price}")
        (
            bid_price,
            ask_price,
            bid_quantity,
            ask_quantity,
        ) = self._compute_order_price_quantity(i, bid_price, ask_price)

        logging.info(
            f"batch {i} bid_price: {bid_price}, ask_price: {ask_price}, bid_quantity: {bid_quantity}, ask_quantity: {ask_quantity}"
        )

        ts = time_ns()
        logging.info(
            f"position direction: {self.position.direction}, residual_reduce_only_quantity: {self.position.residual_reduce_only_quantity}"
        )

        if i == 0:
            if (
                self.position.residual_reduce_only_quantity == 0
                and self.position.net_quantity > 0
            ):
                self.position.residual_reduce_only_quantity = self.position.net_quantity
            else:
                pass
            self.orders["reduce_only_orders"].clear()

        if (self.position.residual_reduce_only_quantity != 0.0) and (i == 0):
            if self.position.direction == "long":
                reduce_only_order = OrderDerivative(
                    price=round(ask_price * 1.01, 4),
                    quantity=round_down(
                        self.position.residual_reduce_only_quantity / 2, 4
                    ),
                    timestamp=ts,
                    side="sell",
                    msg=self.composer.DerivativeOrder(
                        market_id=self.market.market_id,
                        fee_recipient=self.fee_recipient,
                        subaccount_id=self.subaccount_id,
                        price=round(ask_price * 1.01, 4),
                        # FIXME this round_down may cause problem
                        quantity=round_down(
                            self.position.residual_reduce_only_quantity / 2, 4
                        ),
                        leverage=self.leverage,
                        is_buy=False,
                        is_reduce_only=True,
                    ),
                )
                self.orders["reduce_only_orders"].add(reduce_only_order)
                logging.info(
                    f"reduce_only_order {reduce_only_order.msg}"
                )
            elif self.position.direction == "short":
                reduce_only_order = OrderDerivative(
                    price=round(bid_price * 0.99, 4),
                    quantity=round_down(
                        self.position.residual_reduce_only_quantity / 2, 4
                    ),
                    timestamp=ts,
                    side="buy",
                    msg=self.composer.DerivativeOrder(
                        market_id=self.market.market_id,
                        fee_recipient=self.fee_recipient,
                        subaccount_id=self.subaccount_id,
                        price=round(bid_price * 0.99, 4),
                        # FIXME this round_down may cause problem
                        quantity=round_down(
                            self.position.residual_reduce_only_quantity / 2, 4
                        ),
                        leverage=self.leverage,
                        is_buy=True,
                        is_reduce_only=True,
                    ),
                )
                self.orders["reduce_only_orders"].add(reduce_only_order)
                logging.info(
                    f"reduce_only_order {reduce_only_order.msg}"
                )

        ask_order = OrderDerivative(
            price=ask_price,
            quantity=ask_quantity,
            timestamp=ts,
            side="sell",
            msg=self.composer.DerivativeOrder(
                market_id=self.market.market_id,
                fee_recipient=self.fee_recipient,
                subaccount_id=self.subaccount_id,
                price=ask_price,
                quantity=ask_quantity if ask_quantity > 0 else 0.0001,
                leverage=self.leverage,
                is_buy=False,
            ),
        )

        bid_order = OrderDerivative(
            price=bid_price,
            quantity=bid_quantity,
            timestamp=ts,
            side="buy",
            msg=self.composer.DerivativeOrder(
                market_id=self.market.market_id,
                fee_recipient=self.fee_recipient,
                subaccount_id=self.subaccount_id,
                price=bid_price,
                quantity=bid_quantity if bid_quantity > 0 else 0.0001,
                leverage=self.leverage,
                is_buy=True,
            ),
        )

        self.orders["bids"].add(bid_order)
        self.orders["asks"].add(ask_order)
        logging.debug(
            f'bid orders: {self.orders["bids"]}'
        )
        logging.debug(
            f'ask orders: {self.orders["asks"]}'
        )
        logging.debug(
            f"bids: {len(self.orders['bids'])} asks: {len(self.orders['asks'])}"
        )
        if (len(self.orders["reduce_only_orders"]) == 0) or (i != 0):
            return [bid_order.msg, ask_order.msg]
        logging.info(
            f"n reduce_only_orders to replace {i}: {len(self.orders['reduce_only_orders'])}"
        )
        return [bid_order.msg, ask_order.msg] + [
            order.msg for order in self.orders["reduce_only_orders"]
        ]

    async def send_replace_orders(self, i):
        # cancel order by hash
        logging.info(f"bid price {self.bid_price}, ask price: {self.ask_price}")
        logging.info("replace batch %d", i)
        old_orders = self.build_cancel_orders_by_hash_msg(i)
        logging.info("old orders: %s", len(old_orders))

        logging.info("send replace orders")
        new_orders = self.build_place_order_by_price_msg(i)
        logging.info("new orders: %s", len(new_orders))

        logging.info("cancel orders %s", len(old_orders))

        if len(old_orders) != 0:
            logging.info("replace layer %d th orders", i)
            msg = self.composer.MsgBatchUpdateOrders(
                sender=self.address.to_acc_bech32(),
                derivative_orders_to_create=new_orders,
                derivative_orders_to_cancel=old_orders,
            )
            res = await self._send_message(msg, idx=i)
            logging.info("finished replace layer %d th send message %s\n" % (i, res))
        else:
            logging.info("place layer %d orders", i)
            msg = self.composer.MsgBatchUpdateOrders(
                sender=self.address.to_acc_bech32(),
                derivative_orders_to_create=new_orders,
            )
            res = await self._send_message(msg, new_only=True, idx=i)
            logging.info("finished replace layer %d th send message %s\n" % (i, res))
        return res

    async def replace_orders(self):
        logging.info("starting replace orders")

        if len(self.orders["bids"]) != 0 and len(self.orders["asks"]) != 0:
            logging.info("some orders to replace")
            for i in range(self.n_orders):
                await self.send_replace_orders(i)
                logging.info(f"!!!! bid orders {self.orders['bids']}")
                logging.info(f"!!!! ask orders {self.orders['asks']}")
                # await sleep(600)
            logging.info("finished replace orders")
        else:
            logging.info("no orders to replace")
            await self.onetime_get_open_orders()
            for i in range(self.n_orders):
                await self.send_replace_orders(i)
            logging.info("finished replace orders")
        await self.onetime_get_open_orders()
        logging.info("get order hashes")
        logging.info(f"bids: {self.orders['bids']}")
        logging.info(f"asks: {self.orders['asks']}")

    def first_batch(self):
        logging.info("start sending first batches")
        self._build_first_batch_orders()
        logging.debug(f"{self.orders['bids']}")
        logging.debug(f"{self.orders['asks']}")
        logging.warning(
            f"bid orders: {len(self.orders['bids'])}, ask orders: {len(self.orders['asks'])}, reduce_only_orders: {len(self.orders['reduce_only_orders'])}"
        )
        orders = [order.msg for order in self.orders["bids"]] + [
            order.msg for order in self.orders["asks"]
        ]
        if len(self.orders["reduce_only_orders"]):
            orders += [order.msg for order in self.orders["reduce_only_orders"]]
            logging.info(f" sending first batches {len(orders)}")

        logging.debug(f"orders: {orders}")

        msg = self.composer.MsgBatchUpdateOrders(
            sender=self.address.to_acc_bech32(), derivative_orders_to_create=orders
        )
        logging.debug("message: %s", msg)
        return msg

    async def send_first_batch(self):
        if self.position.net_quantity:
            ask_price = self.ask_price
            bid_price = self.bid_price
        else:
            ask_price, bid_price = avellaneda_stoikov_model(
                sigma=self.sigma,
                mid_price=(self.bid_price + self.ask_price) * 0.5,
                limit_horizon=self.limit_horizon,
                quantity=self.position.net_quantity,
                quantity_max=self.position_max,
                kappa=self.kappa,
                gamma=self.gamma,
                dt=self.dt,
                T=self.T,
            )

        self.ask_price = round(ask_price, 4)
        self.bid_price = round(bid_price, 4)
        # FIXME this price is not correct
        self.last_trade_price = round((self.bid_price + self.ask_price) / 2, 4)

        msg = self.first_batch()
        logging.debug(f"first batch msg {msg}")
        res = await self._send_message(msg, new_only=True, idx=0, is_first_batch=True)
        return res

    async def _send_message(
        self,
        msg,
        skip_unpack_msg=True,
        new_only=False,
        update_sequence=False,
        idx: int = 0,
        is_first_batch=False,
    ):
        logging.debug(f"msg: {msg}")
        # build sim tx
        if update_sequence:
            seq = self.address.init_num_seq(self.network.lcd_endpoint).get_sequence()
        else:
            seq = self.address.get_sequence()
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(seq)
            .with_account_num(self.address.get_number())
            .with_chain_id(self.network.chain_id)
        )
        sim_sign_doc = tx.get_sign_doc(self.pub_key)
        sim_sig = self.priv_key.sign(sim_sign_doc.SerializeToString())
        sim_tx_raw_bytes = tx.get_tx_data(sim_sig, self.pub_key)

        # simulate tx
        (sim_res, success) = await self.client.simulate_tx(sim_tx_raw_bytes)
        logging.debug("success: %s sim_res %s" % (success, sim_res))

        if not success:
            logging.info(f"success: {success}")
            logging.info(f"failed in simulate {sim_res}")
            self.address.init_num_seq(self.network.lcd_endpoint)
            raise Exception(f"failed in simulate {sim_res}")

        sim_res_msg = self.composer.MsgResponses(sim_res.result.data, simulation=True)
        logging.debug(f"simulation {sim_res_msg}")

        if not skip_unpack_msg:
            if new_only and is_first_batch:
                logging.debug("unpacking new only response:")
                for i, order in enumerate(self.orders["bids"]):
                    order.order_hash = sim_res_msg[0].derivative_order_hashes[i]

                for i, order in enumerate(self.orders["asks"]):
                    order.order_hash = sim_res_msg[0].derivative_order_hashes[
                        i + len(self.orders["bids"])
                    ]
                for i, order in enumerate(self.orders["reduce_only_orders"]):
                    order.order_hash = sim_res_msg[0].derivative_order_hashes[
                        i + len(self.orders["bids"]) + len(self.orders["asks"])
                    ]
                for order in self.orders["bids"]:
                    logging.info(
                        f"new only: bid order to place, price: {order.price:6.2f}, quantity: {order.quantity:6.4f}, hash: {order.order_hash}"
                    )
                for order in self.orders["asks"]:
                    logging.info(
                        f"new only: ask order to place, price: {order.price:6.2f}, quantity: {order.quantity:6.4f}, hash: {order.order_hash}"
                    )
                if len(self.orders["reduce_only_orders"]) > 0:
                    logging.info(
                        f"new only: reduce only order to place, price: {self.orders['reduce_only_orders'][-1].price:6.2f}, quantity: {self.orders['reduce_only_orders'][-1].quantity:6.4f}, hash: {self.orders['reduce_only_orders'][-1].order_hash}"
                    )

                logging.info("finished unpacking new only response")

            else:
                logging.info("unpacking replace response:")
                self.orders["bids"][-1].order_hash = sim_res_msg[
                    0
                ].derivative_order_hashes[0]

                self.orders["asks"][-1].order_hash = sim_res_msg[
                    0
                ].derivative_order_hashes[1]

                logging.debug(
                    f"bid order to place, price: {self.orders['bids'][-1].price:6.2f}, quantity: {self.orders['bids'][-1].quantity:6.4f}, hash: {self.orders['bids'][-1].order_hash}"
                )
                logging.debug(
                    f"ask order to place, price: {self.orders['asks'][-1].price:6.2f}, quantity: {self.orders['asks'][-1].quantity:6.4f}, hash: {self.orders['asks'][-1].order_hash}"
                )
                if idx == 0 and len(self.orders["reduce_only_orders"]) > 0:
                    self.orders["reduce_only_orders"][-1].order_hash = sim_res_msg[
                        0
                    ].derivative_order_hashes[2]

                    logging.info(
                        f"reduce only order to place, price: {self.orders['reduce_only_orders'][-1].price:6.2f}, quantity: {self.orders['reduce_only_orders'][-1].quantity:6.4f}, hash: {self.orders['reduce_only_orders'][-1].order_hash}"
                    )
                logging.info("finished unpacking replace response")


        # build tx
        gas_price = 500000000
        gas_limit = (
            sim_res.gas_info.gas_used + 20000
        )  # add 20k for gas, fee computation
        fee = [
            self.composer.Coin(
                amount=gas_price * gas_limit,
                denom=self.network.fee_denom,
            )
        ]
        # current_height = await self.client.get_latest_block().block.header.height
        tx = (
            tx.with_gas(gas_limit)
            .with_fee(fee)
            .with_memo("")
            .with_timeout_height(self.client.timeout_height)
        )
        sign_doc = tx.get_sign_doc(self.pub_key)
        sig = self.priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self.pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self.client.send_tx_block_mode(tx_raw_bytes)
        res_msg = self.composer.MsgResponses(res.data)
        logging.debug("tx response")
        logging.debug(res)
        logging.debug("tx msg response")
        logging.debug(res_msg)
        return res_msg
        
    async def balance_stream(self):

        subaccount = await self.client.stream_subaccount_balance(self.subaccount_id)
        async for balance in subaccount:
            # print("Subaccount balance Update:\n")

            self.balance.update_balance(
                available_balance=(
                    float(balance.balance.deposit.available_balance) / 1e18
                ),
                total_balance=(float(balance.balance.deposit.total_balance) / 1e18),
            )
            # print(balance)

    async def trade_stream(self):
        # TODO: figure out which order get filled

        # self.last_trade_price = round(self.bid_price + self.ask_price / 2, 2)
        while True:
            logging.info(f"start trade stream, {self.subaccount_id}")
            trades = await self.client.stream_derivative_trades(
                market_id=self.market.market_id, subaccount_id=self.subaccount_id
            )

            async for trade in trades:
                logging.debug(f"new trade")
                logging.debug(f'bids: {self.orders["bids"]}')
                logging.debug(f'asks: {self.orders["asks"]}')
                if self.last_trade_ts == trade.trade.executed_at:
                    logging.debug(f" duplicate trade")
                else:
                    self.last_trade_ts = trade.trade.executed_at
                    self.last_trade_price = derivative_price_from_backend(
                        trade.trade.position_delta.execution_price,
                        self.market.market_denom,
                    )

                    # TODO check quantity
                    if trade.trade.position_delta.trade_direction == "buy":
                        for order in self.orders["bids"]:
                            if order.order_hash == trade.trade.order_hash:
                                order.quantity -= float(
                                    trade.trade.position_delta.execution_quantity
                                )
                                logging.debug(
                                    f"ask order quantity: {order.quantity} < 0.0001 {order.quantity<=0.0001}"
                                )
                                if order.quantity <= 0.0001:
                                    if self.replace_event.is_set():
                                        logging.debug("order quantity <= 0.0001 is set")
                                    else:
                                        logging.debug("order quantity > 0.0001 is set")
                                        self.price_feed.set()
                            else:
                                logging.debug(
                                    f"buy  price feed is set: {self.price_feed.is_set()}"
                                )
                                if self.price_feed.is_set():
                                    logging.debug("price feed is set")
                                else:
                                    logging.debug("price feed is not set")
                                    self.price_feed.set()
                                logging.debug(f"updated buy orders")

                        # self.orders["bids"].remove(order)
                        # refill orders
                    elif trade.trade.position_delta.trade_direction == "sell":
                        for order in self.orders["asks"]:
                            if order.order_hash == trade.trade.order_hash:
                                order.quantity -= float(
                                    trade.trade.position_delta.execution_quantity
                                )
                                logging.debug(
                                    f"ask order quantity: {order.quantity} < 0.0001: {order.quantity<=0.0001}"
                                )
                                if order.quantity <= 0.0001:
                                    if self.replace_event.is_set():
                                        logging.debug("order quantity <= 0.0001 is set")
                                        pass
                                    else:
                                        logging.debug("order quantity > 0.0001 is set")
                                        self.price_feed.set()
                            else:
                                logging.debug(
                                    f"sell price feed is set: {self.price_feed.is_set()}"
                                )
                                if self.price_feed.is_set():
                                    logging.debug("price feed is set")
                                else:
                                    logging.debug("price feed is not set")
                                    self.price_feed.set()
                                logging.debug(f"updated sell orders")
                    else:
                        logging.error(
                            f"unknown trade direction: {trade.trade.position_delta.trade_direction}"
                        )
                        if self.replace_event.is_set():
                            pass
                        else:
                            self.price_feed.set()
                            logging.error(f"price feed event set")
                        # self.trade_event.set()

    async def get_prices_cycle(self):
        while True:
            logging.debug("get price cycle")
            await self.onetime_oracle_price()
            if self.replace_event.is_set():
                pass
            else:
                if (len(self.orders["bids"]) != self.n_orders) or (
                    len(self.orders["asks"]) != self.n_orders
                ):
                    self.price_feed.set()
            await sleep(self.update_interval * 3.24)

    async def fill_orders(self):
        while True:
            pass

    async def orderbook_stream(self):
        while True:
            logging.info("start orderbook stream")
            orderbooks = await self.client.stream_derivative_orderbook(
                market_id=self.market.market_id
            )
            async for orderbook in orderbooks:
                if len(orderbook.orderbook.buys) >= 1:
                    self.tob_bid_price = derivative_price_from_backend(
                        orderbook.orderbook.buys[0].price, self.market.market_denom
                    )
                if len(orderbook.orderbook.sells) >= 1:
                    self.tob_ask_price = derivative_price_from_backend(
                        orderbook.orderbook.sells[0].price, self.market.market_denom
                    )
                if len(orderbook.orderbook.buys) >= 2:
                    self.sob_best_bid_price = derivative_price_from_backend(
                        orderbook.orderbook.buys[1].price, self.market.market_denom
                    )
                if len(orderbook.orderbook.sells) >= 2:
                    self.sob_best_ask_price = derivative_price_from_backend(
                        orderbook.orderbook.sells[1].price, self.market.market_denom
                    )
                logging.debug(
                    "second_best_bid_price: %s best bid price: %s, best ask price: %s, second_hest ask price %s",
                    self.sob_best_bid_price,
                    self.tob_bid_price,
                    self.tob_ask_price,
                    self.sob_best_ask_price,
                )
                # TODO replace orders

    async def orders_stream(self):
        # TODO this is not needed
        while True:
            logging.info("start orders stream")
            orders = await self.client.stream_derivative_orders(
                market_id=self.market.market_id, subaccount_id=self.subaccount_id
            )
            async for _ in orders:
                pass

    async def position_stream(self):
        while True:
            logging.info("start position stream")
            positions = await self.client.stream_derivative_positions(
                market_id=self.market.market_id, subaccount_id=self.subaccount_id
            )
            async for position in positions:
                if float(position.position.quantity) != 0:
                    if position.position.direction == "long":
                        logging.debug("long position: %s", position)
                        self.position.update(
                            direction="long",
                            quantity=float(position.position.quantity),
                            entry_price=float(position.position.entry_price),
                            margin=float(position.position.margin),
                            liquidation_price=float(
                                position.position.liquidation_price
                            ),
                            mark_price=float(position.position.mark_price),
                            aggregate_reduce_only_quantity=float(
                                position.position.aggregate_reduce_only_quantity
                            ),
                            timestamp=int(position.timestamp),
                        )
                        logging.info("finished update position")
                        if (
                            log(self.position.entry_price)
                            - log(self.position.mark_price)
                            > 0.10
                        ):
                            self.margin_event.set()
                        logging.info("after add margin: %s", self.position.margin)
                    elif position.position.direction == "short":
                        logging.debug("short position: %s", position)
                        self.position.update(
                            direction="short",
                            quantity=float(position.position.quantity),
                            entry_price=float(position.position.entry_price),
                            margin=float(position.position.margin),
                            liquidation_price=float(
                                position.position.liquidation_price
                            ),
                            mark_price=float(position.position.mark_price),
                            aggregate_reduce_only_quantity=float(
                                position.position.aggregate_reduce_only_quantity
                            ),
                            timestamp=int(position.timestamp),
                        )
                        logging.info("finished update position")
                        if (
                            log(self.position.mark_price)
                            - log(self.position.entry_price)
                            > 0.10
                        ):
                            self.margin_event.set()
                        logging.info("after add margin: %s", self.position.margin)
                    else:
                        logging.info("no position")
                else:
                    self.position.update(
                        direction="",
                        quantity=-0.0,
                        entry_price=0.0,
                        margin=0.0,
                        liquidation_price=0.0,
                        mark_price=float(position.position.mark_price),
                        aggregate_reduce_only_quantity=float(
                            position.position.aggregate_reduce_only_quantity
                        ),
                        timestamp=int(position.timestamp),
                    )
                    logging.info("after add margin: %s", self.position.margin)
                logging.info("end of position stream")

    async def compare_and_replace_orders(self):
        await sleep(60)
        while True:
            await self.price_feed.wait()
            logging.info("got signal ")
            # TODO avellaneda_stoikov_model
            mid_price = 0.5 * (self.tob_ask_price + self.tob_bid_price)
            self.ask_price, self.bid_price = avellaneda_stoikov_model(
                sigma=self.sigma,
                mid_price=mid_price,
                limit_horizon=self.limit_horizon,
                quantity=self.position.net_quantity,
                quantity_max=self.position_max,
                kappa=self.kappa,
                gamma=self.gamma,
                dt=self.dt,
                T=self.T,
            )
            if self.last_trade_price and (time() - self.last_trade_ts / 1000):
                self.ask_price = round(
                    max(self.ask_price, self.oracle_price, self.last_trade_price),
                    4,
                )
                self.bid_price = round(
                    min(self.bid_price, self.oracle_price, self.last_trade_price),
                    4,
                )
                logging.info(
                    "all price feeds are good if: updated bid price: %s, ask price: %s\n",
                    self.bid_price,
                    self.ask_price,
                )

            else:
                self.ask_price = round(
                    max(self.ask_price, self.oracle_price),
                    4,
                )
                self.bid_price = round(
                    min(self.bid_price, self.oracle_price),
                    4,
                )

                logging.info(
                    "all price feeds are good else: updated bid price: %s, ask price: %s\n",
                    self.bid_price,
                    self.ask_price,
                )

            # start to replace orders
            if self.bid_price > 0 and (
                (
                    2
                    * (self.ask_price - self.bid_price)
                    / (self.ask_price + self.bid_price)
                )
                < 0.5
            ):
                logging.debug(
                    f"2 * (self.ask_price - self.bid_price) / (self.ask_price + self.bid_price) = {2 * (self.ask_price - self.bid_price) / (self.ask_price + self.bid_price)}>0.5"
                )
                # get the latest orders
                logging.info("good price start get_open_orders")
                await self.onetime_get_open_orders()
                logging.info("good price finish get_open_orders")

                # prices are good, and start update orders
                self.replace_event.set()
                await self.replace_orders()
                logging.info("good price finished replace orders\n")
                self.replace_event.clear()
                self.price_feed.clear()
            else:
                # FIXME  what price to use
                logging.warning(
                    f"bid ask spread too large, oracle price: {self.oracle_price}, bid_price: {self.bid_price}, ask_price: {self.ask_price}"
                )
                logging.debug(
                    f"2 * (self.ask_price - self.bid_price) / (self.ask_price + self.bid_price) = {2 * (self.ask_price - self.bid_price) / (self.ask_price + self.bid_price)}>0.5"
                )
                # get the latest orders
                logging.info("bad price start get_open_orders")
                await self.onetime_get_open_orders()
                logging.info("bad price finish get_open_orders")

                # prices are bad, and start update orders
                self.replace_event.set()
                await self.replace_orders()
                logging.info("bad price finished replace orders\n")
                self.replace_event.clear()
                self.price_feed.clear()

            logging.info("end of compare and replace orders")
            await self.onetime_get_open_orders()
            logging.info("getting new open orders to check if we have missing orders")
            logging.info(
                f"len of bids: {len(self.orders['bids'])}, len of asks: {len(self.orders['asks'])}"
            )
            if (
                (self.orders["bids"][0].quantity == 0)
                or (self.orders["bids"][-1].quantity == 0)
                or (self.orders["asks"][0].quantity == 0)
                or self.orders["asks"][-1].quantity == 0
            ):
                self.price_feed.set()

            logging.info(
                f"finished new open orders, price feed event set: {self.price_feed.is_set()}"
            )

    async def get_oracle_price(self):
        logging.info("getting oracle  price")
        await sleep(self.update_interval)
        while True:
            oracle_prices = await self.client.stream_oracle_prices(
                base_symbol=self.market.base_ticker.upper(),
                quote_symbol=self.market.quote_ticker.upper(),
                oracle_type="pricefeed",
            )
            async for price in oracle_prices:
                logging.debug(f"oracle price: {price.price}, {price.timestamp}")
                if float(price.price) > 0:
                    new_price = float(price.price)  # FIXME
                    # FIXME change this to human readable format
                    logging.info(
                        f"updated oracle  price new price: {new_price}, old price: {self.oracle_price} {datetime.fromtimestamp(int(price.timestamp/1000))}"
                    )
                    if abs(new_price - self.oracle_price) > 0.01:
                        self.oracle_price = new_price
                        self.price_feed.set()
                else:
                    logging.warning("failed to update oracle price")
                    self.oracle_price = -1
                    self.price_feed.set()

    async def onetime_orderbook(self):
        orderbook = await self.client.get_derivative_orderbook(
            market_id=self.market.market_id
        )
        bids = orderbook.orderbook.buys
        asks = orderbook.orderbook.sells

        self.tob_bid_price = derivative_price_from_backend(
            int(bids[0].price), self.market.market_denom
        )
        self.tob_ask_price = derivative_price_from_backend(
            int(asks[0].price), self.market.market_denom
        )

        self.sob_bid_price = derivative_price_from_backend(
            int(bids[1].price), self.market.market_denom
        )
        self.sob_ask_price = derivative_price_from_backend(
            int(asks[1].price), self.market.market_denom
        )

    async def onetime_oracle_price(self):
        oracle_type = "BandIBC"
        oracle_prices = await self.client.stream_oracle_prices(
            base_symbol=self.market.base_ticker,
            quote_symbol=self.market.quote_ticker,
            oracle_type=oracle_type,
        )
        async for oracle_price in oracle_prices:
            self.oracle_price = float(oracle_price.price)

    async def onetime_balance(self):
        # select network: local, testnet, mainnet
        # logging.debug("peggy %s", self.market.quote_peggy)

        balance = await self.client.get_subaccount_balance(
            subaccount_id=self.subaccount_id, denom=self.market.quote_peggy
        )
        # logging.debug("balance: %s", balance)
        self.balance.update_balance(
            available_balance=derivative_price_from_backend(
                balance.balance.deposit.available_balance, self.market.market_denom
            ),
            total_balance=derivative_price_from_backend(
                balance.balance.deposit.total_balance, self.market.market_denom
            ),
        )
        logging.info(
            "available balance: %f, total balance: %f"
            % (self.balance.available_balance, self.balance.total_balance),
        )

    async def onetime_market_info(self):
        market = await self.client.get_derivative_market(
            market_id=self.market.market_id
        )
        self.initial_margin_ratio = float(market.market.initial_margin_ratio)
        self.estimated_fee_ratio = float(market.market.taker_fee_rate)
        logging.info(
            f"market info: initial margin ratio: {self.initial_margin_ratio}, max fee ratio: {self.estimated_fee_ratio}"
        )

    async def onetime_position(self):
        positions = await self.client.get_derivative_positions(
            market_id=self.market.market_id, subaccount_id=self.subaccount_id
        )
        if positions.positions:
            data = positions.positions[0]

            self.position.update(
                direction=data.direction,
                quantity=float(data.quantity),
                entry_price=derivative_price_from_backend(
                    data.entry_price, self.market.market_denom
                ),
                margin=derivative_price_from_backend(
                    data.margin, self.market.market_denom
                ),
                liquidation_price=derivative_price_from_backend(
                    data.liquidation_price, self.market.market_denom
                ),
                mark_price=derivative_price_from_backend(
                    data.mark_price, self.market.market_denom
                ),
                aggregate_reduce_only_quantity=float(
                    data.aggregate_reduce_only_quantity
                ),
                timestamp=time_ns(),
            )
        else:
            pass

    async def onetime_get_open_orders(self):
        self.orders["bids"].clear()
        self.orders["asks"].clear()
        self.orders["reduce_only_orders"].clear()
        logging.debug("clear orders")

        orders = await self.client.get_derivative_orders(
            market_id=self.market.market_id,
            subaccount_id=self.subaccount_id,
        )

        logging.info(f"{len(orders.orders)} open orders")
        if orders.orders:
            for order in orders.orders:
                if (order.order_side == "buy") and (order.is_reduce_only):
                    order_derivative = OrderDerivative(
                        price=derivative_price_from_backend(
                            order.price, self.market.market_denom
                        ),
                        quantity=float(order.quantity),
                        timestamp=0,
                        side="buy",
                        msg=0,
                        order_hash=order.order_hash,
                    )
                    self.orders["reduce_only_orders"].add(order_derivative)
                elif (order.order_side == "sell") and (order.is_reduce_only):
                    order_derivative = OrderDerivative(
                        price=derivative_price_from_backend(
                            order.price, self.market.market_denom
                        ),
                        quantity=float(order.quantity),
                        timestamp=0,
                        side="sell",
                        msg=0,
                        order_hash=order.order_hash,
                    )
                    self.orders["reduce_only_orders"].add(order_derivative)
                elif (order.order_side == "buy") and (not order.is_reduce_only):
                    order_derivative = OrderDerivative(
                        price=derivative_price_from_backend(
                            order.price, self.market.market_denom
                        ),
                        quantity=float(order.quantity),
                        timestamp=0,
                        side="buy",
                        msg=0,
                        order_hash=order.order_hash,
                    )
                    self.orders["bids"].add(order_derivative)
                elif (order.order_side == "sell") and (not order.is_reduce_only):
                    order_derivative = OrderDerivative(
                        price=derivative_price_from_backend(
                            order.price, self.market.market_denom
                        ),
                        quantity=float(order.quantity),
                        timestamp=0,
                        side="sell",
                        msg=0,
                        order_hash=order.order_hash,
                    )
                    self.orders["asks"].add(order_derivative)
                else:
                    logging.warning(
                        f"order state: {type(order.is_reduce_only)} {order.is_reduce_only}"
                    )

            logging.info(
                f"before padding: {len(self.orders['bids'])} bids, {len(self.orders['asks'])} asks, {len(self.orders['reduce_only_orders'])} reduce only orders"
            )
            while len(self.orders["bids"]) < self.n_orders:
                self.orders["bids"].add(
                    OrderDerivative(
                        price=self.bid_price,
                        quantity=0,
                        timestamp=0,
                        side="buy",
                        msg=0,
                        order_hash="",
                    )
                )
            while len(self.orders["asks"]) < self.n_orders:
                self.orders["asks"].add(
                    OrderDerivative(
                        price=self.ask_price,
                        quantity=0,
                        timestamp=0,
                        side="sell",
                        msg=0,
                        order_hash="",
                    )
                )
            for order in self.orders["bids"]:
                logging.info(
                    f"bid price:{order.price:.4f}, quantity:{order.quantity:.4f}, ts:{order.timestamp}, hash:{order.order_hash}"
                )
            for order in self.orders["asks"]:
                logging.info(
                    f"ask price:{order.price:.4f}, quantity:{order.quantity:.4f}, ts:{order.timestamp}, hash:{order.order_hash}"
                )
            logging.info(
                f"after padding: {len(self.orders['bids'])} bids, {len(self.orders['asks'])} asks"
            )

    async def onetime_get_and_replace_orders(self):
        if (self.tob_bid_price - self.sob_bid_price) / self.sob_bid_price < 0.01:
            self.bid_price = self.tob_bid_price
        else:
            self.bid_price = self.sob_bid_price

        if (self.sob_ask_price - self.tob_ask_price) < 0.01:
            self.ask_price = self.tob_ask_price
        else:
            self.ask_price = self.sob_ask_price

        await sleep(3)
        await self.onetime_get_open_orders()

        if len(self.orders["bids"]) != 0:
            logging.info(
                f"have open orders:{len(self.orders['bids'])} bid orders, {len(self.orders['asks'])} ask orders"
            )
            for i in range(self.n_orders):
                await self.send_replace_orders(i)
                logging.info(f"!!!! bid orders: {self.orders['bids']}")
                logging.info(f"!!!! ask orders: {self.orders['asks']}")
        else:
            logging.info("no open orders")
            res = await self.send_first_batch()
            logging.info(f"res {res}")

    ## place
    async def cancel_by_market_id(self):
        msg = self.composer.MsgBatchUpdateOrders(
            sender=self.address.to_acc_bech32(),
            subaccount_id=self.subaccount_id,
            derivative_market_ids_to_cancel_all=[self.market.market_id],
        )
        await self._send_message(msg, skip_unpack_msg=True)

    async def increase_margin(self):
        # prepare tx msg
        while True:
            await self.margin_event.wait()
            logging.info("got increase_margin event")
            msg = self.composer.MsgIncreasePositionMargin(
                sender=self.address.to_acc_bech32(),
                market_id=self.market.market_id,
                source_subaccount_id=self.subaccount_id,
                destination_subaccount_id=self.subaccount_id,
                amount=round(self.position.margin * 0.15, 4),
            )
            await self._send_message(msg, skip_unpack_msg=True)
            self.margin_event.clear()
            logging.info("finished increase_margin event")

    async def close(self):
        logging.info("closing all open channels")
        await self.client.close_chain_channel()
        await self.client.close_exchange_channel()
        logging.info("closed all open channels")

    async def market_making_strategy(self):
        await self.client.sync_timeout_height()
        logging.info(f"start sending first batch of orders")
        # update orderbook to start algo
        await self.onetime_orderbook()
        await self.onetime_balance()

        await self.onetime_market_info()
        await self.onetime_position()

        await sleep(10)
        logging.info(
            f"open position: entry_price: {self.position.entry_price}, net_quantity: {self.position.net_quantity}"
        )
        await self.onetime_get_and_replace_orders()

        logging.info(f"sent first batch of orders\n")

        tasks = (
            self.compare_and_replace_orders,
            self.orderbook_stream,
            self.position_stream,
            self.trade_stream,
            self.increase_margin,
            self.get_prices_cycle,
        )
        exception_aware_task = create_task(
            self._exception_aware_scheduler(*tasks), name="exception_aware_scheduler"
        )
        exception_aware_task.add_done_callback(_handle_task_result)

        await exception_aware_task
        logging.info("finished tasks")

    async def _exception_aware_scheduler(self, *task_definitions):
        tasks = {
            create_task(coro(), name=coro.__name__): coro for coro in task_definitions
        }
        logging.debug(f"Created tasks: {tasks}")
        while tasks:
            logging.info(f"Starting tasks")
            done, pending = await wait(tasks.keys(), return_when=FIRST_EXCEPTION)
            for task in done:
                if task.exception() is not None:
                    msg = str(task.exception())
                    if "account sequence mismatch" in msg:
                        self.node_index, self.network, insecure = switch_network(
                            self.nodes, 0, self.is_mainnet
                        )
                        self.client, self.composer = build_client_and_composer(
                            self.network, insecure
                        )
                        logging.error("Task exited with exception:")
                        task.print_stack()
                        logging.info(f"Rescheduling the task: {task.get_name()}\n")
                        coro = tasks.pop(task)
                        tasks[create_task(coro())] = coro
                    elif "Socket closed" in msg:
                        logging.error("Task exited with exception:")
                        task.print_stack()
                        logging.info(f"Rescheduling the task: {task.get_name()}\n")
                        coro = tasks.pop(task)
                        tasks[create_task(coro())] = coro
                    else:
                        logging.error(
                            f"Task exited with exception: {task.get_name()}\n"
                        )
                        task.print_stack()
                        raise Exception(msg)
