from abc import ABC, abstractmethod
from configparser import ConfigParser
from decimal import Decimal
from enum import Enum
from typing import Tuple, Optional, List
from asyncio import Queue, sleep, gather, ensure_future, run

from hashlib import sha256
from time import time
from hmac import new
from aiohttp import TCPConnector, ClientSession

# from decouple import config as env_config


from pyinjective.async_client import AsyncClient
from pyinjective.constant import Network
from pyinjective.composer import Composer
from pyinjective.transaction import Transaction
from pyinjective.wallet import PrivateKey


class State(Enum):
    BUY = 1
    SELL = 2
    BOTH = 3
    NONE = 4


class Strategy(ABC):
    """
    Strategy interface
    """

    @abstractmethod
    def update(self, exchange_client) -> None:
        """
        Get an event update from the exchange client
        """
        pass

    @abstractmethod
    async def place_orders(self):
        pass

    @abstractmethod
    async def cancel_orders(self):
        pass


class InjectiveSpotStrategy(Strategy):
    def __init__(
        self,
        base: str,
        quote: str,
        config: ConfigParser,
        network: Network,
        fee_recipient: str,
        private_key: str,
        min_base_balance: float = 10,
        min_quote_balance: float = 10,
        min_order_size: float = 1,
    ):
        self._base = base if base != "eth" else "weth"
        self._quote = quote
        self._market_id = get_market_id(base, quote, config)
        self._gas_price = 500000000

        self._client = AsyncClient(network=network, insecure=True)

        self._composer = Composer(network=network.string())

        # load account
        self._fee_recipient = fee_recipient
        self._network = network
        self._priv_key = PrivateKey.from_hex(private_key)
        self._pub_key = self._priv_key.to_public_key()

        self._address = self._pub_key.to_address().init_num_seq(network.lcd_endpoint)
        self._subaccount_id = self._address.get_subaccount_id(index=0)
        self._orders = Queue(maxsize=20)

        self._base_balance = 0  # placeholder
        self._quote_balance = 0  # placeholder
        self._min_order_size = min_order_size
        self._state = State.BOTH
        self._min_base_balance = min_base_balance
        self._min_quote_balance = min_quote_balance
        # self._placed_orders = {}

        self._base_asset_multiplier = get_base_asset_multiplier(self._market_id, config)
        self._quote_asset_multiplier = get_quote_asset_multiplier(
            self._market_id, config
        )

        # [binance_best_bid_price, binance_best_ask_price, injective_best_bid_price, injective_best_ask_price]
        self._prices = [0.0, 0.0, 0.0, 0.0]
        self._prev_prices = self._prices[:]

    def update(self, exchange_client) -> None:
        if isinstance(exchange_client, BinanceSpotClient):
            if (
                self._prices[0] != exchange_client.best_bid_price
                and self._prices[1] != exchange_client.best_ask_price
            ):
                self._prices[:2] = [
                    exchange_client.best_bid_price,
                    exchange_client.best_ask_price,
                ]
            elif (
                self._prices[0] != exchange_client.best_bid_price
                and self._prices[1] == exchange_client.best_ask_price
            ):
                self._prices[0] = exchange_client.best_bid_price
            elif (
                self._prices[0] == exchange_client.best_bid_price
                and self._prices[1] != exchange_client.best_ask_price
            ):
                self._prices[1] = exchange_client.best_ask_price
            else:
                pass
        else:
            if (
                self._prices[2] != exchange_client.best_bid_price
                and self._prices[3] != exchange_client.best_ask_price
            ):
                self._prices[2:] = [
                    exchange_client.best_bid_price,
                    exchange_client.best_ask_price,
                ]
            elif (
                self._prices[2] != exchange_client.best_bid_price
                and self._prices[3] == exchange_client.best_ask_price
            ):
                self._prices[2] = exchange_client.best_bid_price
            elif (
                self._prices[2] == exchange_client.best_bid_price
                and self._prices[3] != exchange_client.best_ask_price
            ):
                self._prices[3] = exchange_client.best_ask_price
            else:
                pass
            pass

    async def get_base_asset_balance(self):
        balance = await self._client.get_subaccount_balance(
            subaccount_id=self._subaccount_id, denom=self._base
        )
        self._base_balance = float(
            Decimal(balance.balance.deposit.available_balance)
            / 10 ** self._base_asset_multiplier
        )

    async def get_quote_asset_balance(self):
        balance = await self._client.get_subaccount_balance(
            subaccount_id=self._subaccount_id,
            denom="peggy0x69efCB62D98f4a6ff5a0b0CFaa4AAbB122e85e08",
        )
        self._quote_balance = float(
            Decimal(balance.balance.deposit.available_balance)
            / 10 ** self._quote_asset_multiplier
        )

    async def place_and_replace_orders(self):
        print("start place orders is running")
        """
        You can add your own logic here to place and cancel orders.
        """
        while True:
            if not self._orders.empty():
                if self._orders.qsize() == 2:
                    (res_msg, sim_res_msg) = await self._batch_cancel_spot_orders()
                else:
                    pass

            if self._state == State.BOTH:
                # sufficient balance in base asset and quote asset, place two orders
                if (self._prices != self._prev_prices) and (0 not in self._prices):
                    if (
                        self._base_balance <= self._min_base_balance
                        and self._quote_balance <= self._min_quote_balance
                    ):
                        self._state = State.NONE
                    elif self._base_balance <= self._min_base_balance:
                        self._state = State.BUY
                    elif self._quote_balance <= self._min_quote_balance:
                        self._state = State.SELL
                    else:
                        orders_list = [
                            (
                                round(self._prices[0] * 0.5, 2),
                                self._min_order_size,
                                True,
                            ),
                            (
                                round(self._prices[1] * 2.0, 4),
                                self._min_order_size,
                                False,
                            ),
                        ]
                        self._quote_balance -= self._min_order_size
                        self._base_balance -= self._min_order_size
                        (
                            res_msg,
                            sim_res_msg,
                        ) = await self._batch_create_spot_limit_orders(orders_list)
                else:
                    await sleep(1)
            elif self._state == State.BUY:
                # no enough balance in base asset, place sell order on quote asset
                (res_msg, sim_res_msg) = await self._create_spot_limit_order(
                    round(self._prices[0] * 0.5, 2), self._min_order_size, True
                )
                self._quote_balance -= self._min_order_size
            elif self._state == State.SELL:
                # no enough balance in quote asset, place sell order on base asset
                (res_msg, sim_res_msg) = await self._create_spot_limit_order(
                    round(self._prices[0] * 2, 2), self._min_order_size, False
                )
                self._base_balance -= self._min_order_size
            elif self._state == State.NONE:
                # no enough balance to place orders, so we keep checking for changes in balance
                if (
                    self._base_balance > self._min_base_balance
                    and self._quote_balance >= self._min_quote_balance
                ):
                    self._state = State.BOTH
                elif (
                    self._base_balance <= self._min_base_balance
                    and self._quote_balance > self._min_quote_balance
                ):
                    self._state = State.BUY
                elif (
                    self._quote_balance <= self._min_quote_balance
                    and self._base_balance > self._min_base_balance
                ):
                    self._state = State.SELL
                else:
                    pass

    async def place_orders(self):
        print("start place orders is running")
        while True:
            if self._state == State.BOTH:
                if (self._prices != self._prev_prices) and (0 not in self._prices):
                    if (
                        self._base_balance <= self._min_base_balance
                        and self._quote_balance <= self._min_quote_balance
                    ):
                        self._state = State.NONE
                    elif self._base_balance <= self._min_base_balance:
                        self._state = State.BUY
                    elif self._quote_balance <= self._min_quote_balance:
                        self._state = State.SELL
                    else:
                        orders_list = [
                            (
                                round(self._prices[0] * 0.5, 2),
                                self._min_order_size,
                                True,
                            ),
                            (
                                round(self._prices[1] * 2.0, 4),
                                self._min_order_size,
                                False,
                            ),
                        ]
                        self._quote_balance -= self._min_order_size
                        self._base_balance -= self._min_order_size
                        (
                            res_msg,
                            sim_res_msg,
                        ) = await self._batch_create_spot_limit_orders(orders_list)
                else:
                    await sleep(0.3)
            elif self._state == State.BUY:
                (res_msg, sim_res_msg) = await self._create_spot_limit_order(
                    round(self._prices[0] * 0.5, 2), self._min_order_size, True
                )
                self._quote_balance -= self._min_order_size
            elif self._state == State.SELL:
                (res_msg, sim_res_msg) = await self._create_spot_limit_order(
                    round(self._prices[0] * 2, 2), self._min_order_size, False
                )
                self._base_balance -= self._min_order_size
            elif self._state == State.NONE:
                if self._base_balance > 0 and self._quote_balance >= 0:
                    self._state = State.BOTH
                elif self._base_balance <= 0 and self._quote_balance > 0:
                    self._state = State.BUY
                elif self._quote_balance <= 0 and self._base_balance > 0:
                    self._state = State.SELL
                else:
                    pass

    async def cancel_orders(self):
        print("start cancel orders is running")
        while True:
            if self._orders.empty():
                await sleep(0.3)
            else:
                if self._orders.qsize() == 2:
                    (res_msg, sim_res_msg) = await self._batch_cancel_spot_orders()
                elif self._orders.qsize == 1:
                    (res_msg, sim_res_msg) = await self._cancel_spot_limit_order()
                else:
                    pass

    async def _simulate_transcation(
        self, tx: Transaction
    ) -> Tuple[Optional[int], Optional[List]]:
        sim_sign_doc = tx.get_sign_doc(self._pub_key)
        sim_sig = self._priv_key.sign(sim_sign_doc.SerializeToString())
        sim_tx_raw_bytes = tx.get_tx_data(sim_sig, self._pub_key)

        # simulate tx
        (sim_res, success) = await self._client.simulate_tx(sim_tx_raw_bytes)
        if not success:
            return (None, None)

        sim_res_msg = Composer.MsgResponses(sim_res.result.data, simulation=True)

        return (sim_res.gas_info.gas_used, sim_res_msg)

    async def _create_spot_limit_order(
        self, price: float, quantity: float, is_buy: bool, simulation: bool = True
    ):
        # prepare tx msg
        msg = self._composer.MsgCreateSpotLimitOrder(
            sender=self._address.to_acc_bech32(),
            market_id=self._market_id,
            subaccount_id=self._subaccount_id,
            fee_recipient=self._fee_recipient,
            price=price,
            quantity=quantity,
            is_buy=is_buy,
        )

        # build sim tx
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(self._address.get_sequence())
            .with_account_num(self._address.get_number())
            .with_chain_id(self._network.chain_id)
        )
        if simulation:
            (gas_used, sim_res_msg) = await self._simulate_transcation(tx)
            if gas_used is None:
                gas_limit = 165000
            else:
                gas_limit = gas_used + 15000
        else:
            gas_limit = 165000
            sim_res_msg = None

        # build tx
        fee = [
            self._composer.Coin(
                amount=self._gas_price * gas_limit,
                denom=self._network.fee_denom,
            )
        ]

        tx = tx.with_gas(gas_limit).with_fee(fee).with_memo("").with_timeout_height(0)
        sign_doc = tx.get_sign_doc(self._pub_key)
        sig = self._priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self._pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = Composer.MsgResponses(res.data)

        self._orders.put_nowait(res_msg[0])
        self._orders.put_nowait((res_msg[0], (price, quantity, is_buy)))

        if sim_res_msg is not None:
            return (res_msg, sim_res_msg)
        else:
            return (res_msg, None)

    async def _cancel_spot_limit_order(self, simulation=False):
        order_tuple = self._orders.get_nowait()

        # prepare tx msg
        msg = self._composer.MsgCancelSpotOrder(
            sender=self._address.to_acc_bech32(),
            market_id=self._market_id,
            subaccount_id=self._subaccount_id,
            order_hash=order_tuple[0].order_hash,
        )

        # build sim tx
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(self._address.get_sequence())
            .with_account_num(self._address.get_number())
            .with_chain_id(self._network.chain_id)
        )
        if simulation:
            (gas_used, sim_res_msg) = await self._simulate_transcation(tx)
            if gas_used is None:
                gas_limit = 165000
            else:
                gas_limit = gas_used + 15000
        else:
            gas_limit = 165000
            sim_res_msg = None

        fee = [
            self._composer.Coin(
                amount=self._gas_price * gas_limit,
                denom=self._network.fee_denom,
            )
        ]
        tx = tx.with_gas(gas_limit).with_fee(fee).with_memo("").with_timeout_height(0)
        sign_doc = tx.get_sign_doc(self._pub_key)
        sig = self._priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self._pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = Composer.MsgResponses(res.data)
        if order_tuple[1][2]:
            self._quote_balance += order_tuple[1][0] * order_tuple[1][1]
        else:
            self._base_balance += order_tuple[1][1]
        if sim_res_msg is not None:
            return (res_msg, sim_res_msg)
        return (res_msg, None)

    async def _batch_create_spot_limit_orders(
        self, orders_list: List[Tuple[float, float, bool]], simulation: bool = True
    ):
        orders = [
            self._composer.SpotOrder(
                market_id=self._market_id,
                subaccount_id=self._subaccount_id,
                fee_recipient=self._fee_recipient,
                price=price,
                quantity=quantity,
                is_buy=is_buy,
            )
            for (price, quantity, is_buy) in orders_list
        ]

        # prepare tx msg
        msg = self._composer.MsgBatchCreateSpotLimitOrders(
            sender=self._address.to_acc_bech32(), orders=orders
        )

        # build sim tx
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(self._address.get_sequence())
            .with_account_num(self._address.get_number())
            .with_chain_id(self._network.chain_id)
        )

        if simulation:
            (gas_used, sim_res_msg) = await self._simulate_transcation(tx)
            # order_hash in sim_res_msg
            if gas_used is None:
                gas_limit = max(150000 * len(orders), 165000)
            else:
                gas_limit = gas_used + 15000
        else:
            gas_limit = max(150000 * len(orders), 165000)
            sim_res_msg = None
        fee = [
            self._composer.Coin(
                amount=self._gas_price * gas_limit,
                denom=self._network.fee_denom,
            )
        ]
        tx = tx.with_gas(gas_limit).with_fee(fee).with_memo("").with_timeout_height(0)
        sign_doc = tx.get_sign_doc(self._pub_key)
        sig = self._priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self._pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = Composer.MsgResponses(res.data)
        for idx, order_hash in enumerate(res_msg[0].order_hashes):
            self._orders.put_nowait((order_hash, orders_list[idx]))

        if simulation:
            if sim_res_msg is not None:
                return (res_msg, sim_res_msg)
        return (res_msg, None)

    async def _batch_cancel_spot_orders(self):
        orders = []
        orders_detail = []
        while not self._orders.empty():
            order_tuple = self._orders.get_nowait()
            orders.append(
                self._composer.OrderData(
                    market_id=self._market_id,
                    subaccount_id=self._subaccount_id,
                    order_hash=order_tuple[0],
                )
            )
            orders_detail.append(order_tuple[1])

        # prepare tx msg
        msg = self._composer.MsgBatchCancelSpotOrders(
            sender=self._address.to_acc_bech32(), data=orders
        )

        # build sim tx
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(self._address.get_sequence())
            .with_account_num(self._address.get_number())
            .with_chain_id(self._network.chain_id)
        )

        (gas_used, sim_res_msg) = await self._simulate_transcation(tx)
        # order_hash in sim_res_msg
        if gas_used is None:
            gas_limit = max(150000 * len(orders), 165000)
        else:
            gas_limit = gas_used + 15000
        fee = [
            self._composer.Coin(
                amount=self._gas_price * gas_limit,
                denom=self._network.fee_denom,
            )
        ]
        tx = tx.with_gas(gas_limit).with_fee(fee).with_memo("").with_timeout_height(0)
        sign_doc = tx.get_sign_doc(self._pub_key)
        sig = self._priv_key.sign(sign_doc.SerializeToString())
        tx_raw_bytes = tx.get_tx_data(sig, self._pub_key)

        # broadcast tx: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)

        for order_detail in orders_detail:
            if order_detail[2]:
                self._quote_balance += order_detail[0] * order_detail[1]
            else:
                self._base_balance += order_detail[1]

        res_msg = Composer.MsgResponses(res.data)
        if sim_res_msg is not None:
            return (res_msg, sim_res_msg)
        return (res_msg, None)


class ExchangeClient(ABC):
    """
    ExchangeClient interface
    """

    @abstractmethod
    def attach(self, strategy) -> None:
        """
        Attach market to strategy
        """

    @abstractmethod
    def detach(self, strategy) -> None:
        """
        Detach market from strategy
        """

    @abstractmethod
    def update_strategies(self) -> None:
        """
        Notify all strategies about an event.
        """


class InjectiveSpotClient(ExchangeClient):
    def __init__(self, base: str, quote: str, config: ConfigParser, network: Network):
        self._base = base if base != "eth" else "weth"
        self._quote = quote
        self._strategies = []

        self._market_id = get_market_id(base, quote, config)
        self._price_multiplier = get_price_multiplier(self._market_id, config)
        self._quantity_multiplier = get_quantity_multiplier(self._market_id, config)
        self._client = AsyncClient(network=network, insecure=True)

        self.last_timestamp = 0
        self.best_bid_price = 0
        self.best_ask_price = 0
        self.best_bid_quantity = 0
        self.best_ask_quantity = 0

    async def close(self) -> None:
        await self._client.exchange_channel.close()

    def attach(self, strategy) -> None:
        """
        Attach market to strategy
        """
        self._strategies.append(strategy)

    def detach(self, strategy) -> None:
        """
        Detach market from strategy
        """
        self._strategies.remove(strategy)

    def update_strategies(self) -> None:
        """
        Notify all strategies about an event.
        """
        for strategy in self._strategies:
            strategy.update(self)

    async def orderbook(self) -> None:
        print("injective spot client is running")
        orderbook = await self._client.stream_spot_orderbook(market_id=self._market_id)
        async for orders in orderbook:
            self.last_timestamp = orders.timestamp
            self.best_bid_price = float(
                round(
                    Decimal(orders.orderbook.buys[0].price) * self._price_multiplier, 4
                )
            )
            self.best_ask_price = float(
                round(
                    Decimal(orders.orderbook.sells[0].price) * self._price_multiplier, 4
                )
            )
            self.best_bid_quantity = float(
                Decimal(orders.orderbook.buys[0].quantity) * self._quantity_multiplier
            )
            self.best_ask_quantity = float(
                Decimal(orders.orderbook.sells[0].quantity) * self._quantity_multiplier
            )
            self.update_strategies()


class BinanceSpotClient(ExchangeClient):
    def __init__(self, base: str, quote):
        self._base = base
        self._quote = quote
        self._strategies = []
        self._client = ClientSession()
        self.url = (
            f"wss://stream.binance.com:9443/ws/{self._base}{self._quote}@depth5@1000ms"
        )

        self.last_timestamp = 0
        self.best_bid_price = 0
        self.best_ask_price = 0
        self.best_bid_quantity = 0
        self.best_ask_quantity = 0

    async def close(self) -> None:
        await self._client.close()

    def attach(self, strategy) -> None:
        """
        Attach market to strategy
        """
        self._strategies.append(strategy)

    def detach(self, strategy) -> None:
        """
        Detach market from strategy
        """
        self._strategies.remove(strategy)

    def update_strategies(self) -> None:
        """
        Notify all strategies about an event.
        """
        for strategy in self._strategies:
            strategy.update(self)

    async def orderbook(self) -> None:
        print("binance spot client is running")
        async with self._client.ws_connect(self.url) as orderbook:
            async for orders in orderbook:
                data = orders.json()
                self.best_bid_price = float(data["bids"][0][0])
                self.best_ask_price = float(data["asks"][0][0])
                self.best_bid_quantity = float(data["bids"][0][1])
                self.best_ask_quantity = float(data["asks"][0][1])
                self.update_strategies()


#  =======  helper functions =======
def get_price_multiplier(market_id: str, config: ConfigParser) -> Decimal:
    price_multiplier = Decimal(
        config[market_id]["min_display_price_tick_size"]
    ) / Decimal(config[market_id]["min_price_tick_size"])
    return price_multiplier


def get_quantity_multiplier(market_id: str, config: ConfigParser) -> Decimal:
    quantity_multiplier = Decimal(
        config[market_id]["min_display_quantity_tick_size"]
    ) / Decimal(config[market_id]["min_quantity_tick_size"])
    return quantity_multiplier


def get_base_asset_multiplier(market_id: str, config: ConfigParser) -> Decimal:
    price_multiplier = Decimal(config[market_id]["base"])
    return price_multiplier


def get_quote_asset_multiplier(market_id: str, config: ConfigParser) -> Decimal:
    price_multiplier = Decimal(config[market_id]["quote"])
    return price_multiplier


def get_market_id(base: str, quote: str, config: ConfigParser, is_spot=True) -> str:

    markets = dict()
    for key in config.keys():
        try:
            x = config[key]["description"][1:-1].split(" ", 4)
            if len(x) == 3:
                _base, _quote = x[2].split("/")
                markets[f"{x[1].lower()}_{_base.lower()}_{_quote.lower()}"] = key
            else:
                _base, _quote = x[2].split("/")
                markets[f"{x[3].lower()}_{_base.lower()}_{_quote.lower()}"] = key
        except:
            pass

    if is_spot:
        if base == "eth":
            base = "weth"
        return markets["spot_" + base.lower() + "_" + quote.lower()]
    return markets["perp_" + base.lower() + "_" + quote.lower()]


async def run_all(
    ini_config: ConfigParser,
    network: Network,
    inj_key: str,
    private_key: str,
    base: str,
    quote: str,
    min_base_asset_balance: float,
    min_quote_asset_balance: float,
    min_order_size=float,
):
    """
    set up all clients
    """
    injective_strategy = InjectiveSpotStrategy(
        base,
        quote,
        ini_config,
        network,
        fee_recipient=inj_key,
        private_key=private_key,
        min_base_balance=min_base_asset_balance,
        min_quote_balance=min_quote_asset_balance,
        min_order_size=min_order_size,
    )
    injective = InjectiveSpotClient(base, quote, ini_config, network)
    injective.attach(injective_strategy)
    binance = BinanceSpotClient(base, quote)
    binance.attach(injective_strategy)

    # initialize base asset and quote asset balance
    await injective_strategy.get_base_asset_balance()
    await injective_strategy.get_quote_asset_balance()

    jobs = [
        ensure_future(injective_strategy.place_and_replace_orders()),
        ensure_future(injective.orderbook()),
        ensure_future(binance.orderbook()),
    ]
    await gather(*jobs)


def run_cross_exchange_market_making(config, ini_config):
    """
    start the market maker strategy
    """

    inj_key = config["inj_chain_addr"]
    private_key = config["private_key"]
    base = config["base_asset"]
    quote = config["quote_asset"]
    min_base_asset_balance = float(config["min_base_asset_balance"])
    min_quote_asset_balance = float(config["min_quote_asset_balance"])
    min_order_size = float(config["min_order_size"])

    if config["is_mainnet"] == "true":
        network = Network.mainnet()
    else:
        network = Network.testnet()

    if isinstance(inj_key, str) and isinstance(private_key, str):
        run(
            run_all(
                ini_config,
                network,
                inj_key,
                private_key,
                base=base,
                quote=quote,
                min_base_asset_balance=min_base_asset_balance,
                min_quote_asset_balance=min_quote_asset_balance,
                min_order_size=min_order_size,
            )
        )
    else:
        print("Error in INJ KEY AND PRIVIATE KEY", type(inj_key), type(private_key))
