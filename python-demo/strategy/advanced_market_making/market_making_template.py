from asyncio import (
    Event,
)
import logging
from pyinjective.wallet import PrivateKey

from sortedcontainers import SortedList
from core.object import (
    PositionDerivative,
    MarketDerivative,
    BalanceDerivative,
)
from configparser import SectionProxy
from typing import List, Dict
from util.misc import (
    build_client_and_composer,
    switch_network,
)


class MarketMaker:
    def __init__(
        self,
        configs: SectionProxy,
    ):
        priv_key = configs["private_key"]
        nodes = configs["nodes"].split(",")
        self.nodes = nodes
        self.is_mainnet = configs.getboolean("is_mainnet", False)
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
        self.update_interval = configs.getint("update_interval", 60)
        logging.info("update interval: %d" % self.update_interval)

        ############################
        self.position = PositionDerivative()

        if configs.get("base") and configs.get("quote"):
            self.market = MarketDerivative(
                base=configs["base"],
                quote=configs["quote"],
                network=self.network,
                is_mainnet=self.is_mainnet,
            )
        else:
            raise Exception("invalid base or quote ticker")
        self.balance = BalanceDerivative(
            available_balance=configs.getfloat("available_balance", 10.0)
        )

        self.ask_price = 0
        self.bid_price = 0

        self.n_orders = configs.getint("n_orders", 5)
        logging.info("n_orders: %s" % self.n_orders)
        self.leverage = configs.getfloat("leverage", 1)
        logging.info("leverage: %s" % self.leverage)

        # Avellaneda Stoikov model parameters

        self.orders: Dict[str, SortedList] = {
            "bids": SortedList(),
            "asks": SortedList(),
            "reduce_only_orders": SortedList(),
        }

        self.tob_bid_price = 0.0
        self.sob_best_bid_price = 0.0
        self.tob_ask_price = 0.0
        self.sob_best_ask_price = 0.0

        self.last_order_delta = configs.getfloat("last_order_delta", 0.02)
        self.first_order_delta = configs.getfloat("first_order_delta", 0.00)
        logging.info(
            "first_order_delta: %s, last_order_delta: %s :"
            % (self.first_order_delta, self.last_order_delta)
        )

        self.first_asset_allocation = configs.getfloat("first_asset_allocation", 0)
        self.last_asset_allocation = configs.getfloat("last_asset_allocation", 0.4)

        self.estimated_fee_ratio = configs.getfloat("estimated_fee_ratio", 0.005)
        self.initial_margin_ratio = 1

        self.bid_total_asset_allocation = configs.getfloat(
            "bid_total_asset_allocation", 0.09
        ) * (
            1 - self.estimated_fee_ratio
        )  # fraction of total asset
        logging.info("bid_total_asset_allocation: %s" % self.bid_total_asset_allocation)
        self.ask_total_asset_allocation = configs.getfloat(
            "ask_total_asset_allocation", 0.11
        ) * (
            1 - self.estimated_fee_ratio
        )  # fraction of total asset
        logging.info("ask_total_asset_allocation: %s" % self.ask_total_asset_allocation)
