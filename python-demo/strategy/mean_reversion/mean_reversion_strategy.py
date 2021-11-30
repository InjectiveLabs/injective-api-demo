import os
import asyncio
from abc import ABC, abstractmethod
from configparser import ConfigParser
from decimal import Decimal
from time import sleep
import datetime as dt
from typing import Tuple, List, Optional

from pyinjective.async_client import AsyncClient
from pyinjective.constant import Network
from pyinjective.composer import Composer as ProtoMsgComposer
from pyinjective.transaction import Transaction
from pyinjective.wallet import PrivateKey

from .data_manager import SmaDataManager


_main_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class Strategy(ABC):
    """
   Strategy interface
   """

    @abstractmethod
    async def _place_mkt_orders(self):
        pass

    @abstractmethod
    async def _cancel_orders(self):
        pass


class InjectiveSpotStrategy(Strategy):
    """
    Injective Spot Trading Strategies
    """
    def __init__(self, configs: ConfigParser):
        """

        Args:
            configs: ConfigParser | config of credential and strategies in configs.ini file
        """
        # set trading pairs
        self._strategy_name = configs.get("strategy_name")
        self._base_asset = configs.get('base_asset').upper()
        self._quote_asset = configs.get('quote_asset').upper()
        self._pair = self._base_asset + "/" + self._quote_asset
        self._gas_price = 500000000

        # mainnet or testnet
        if configs.getboolean('is_mainnet'):
            print('main_net')
            self._network = Network.mainnet()
            ini_filename = "denoms_mainnet.ini"
        else:
            print('test_net')
            self._network = Network.testnet()
            ini_filename = "denoms_testnet.ini"

        print(f'========== Start to trading on Injective ==========')
        print(f"Network: {'mainnet' if configs.getboolean('is_mainnet') else 'testnet'}")
        print(f'Trading pairs: {self._pair}')

        # create grpc client and composer for API communication
        self._client = AsyncClient(self._network, insecure=True)
        self._composer = ProtoMsgComposer(network=self._network.string())

        print('Authorising......')
        # read and assign the credentials
        self._fee_recipient = configs.get('fee_recipient')
        self._inj_chain_addr = configs.get('inj_chain_addr')
        self._priv_key = PrivateKey.from_hex(configs['private_key'])
        self._pub_key = self._priv_key.to_public_key()
        loop = asyncio.get_event_loop()
        # get eth chain address
        loop.run_until_complete(self._get_address())
        # get sub account id
        loop.run_until_complete(self._get_account_id())

        # get market_id from currency pair
        pairs = ConfigParser()
        pairs.read(os.path.join(_main_dir, "pairs_to_market_id.ini"))
        self._market_id = pairs[f"Spot {self._pair}"]['market_id']

        # read network configs according to the market_id
        network_config = ConfigParser()
        network_config.read(os.path.join(_main_dir, ini_filename))
        self._description = network_config[self._market_id]['description']
        self._base_ = network_config[self._market_id]['base']
        self._quote_ = network_config[self._market_id]['quote']
        min_price_tick_size = network_config[self._market_id]['min_price_tick_size']
        min_display_price_tick_size = network_config[self._market_id]['min_display_price_tick_size']
        min_quantity_tick_size = network_config[self._market_id]['min_quantity_tick_size']
        min_display_quantity_tick_size = network_config[self._market_id]['min_display_quantity_tick_size']

        # set price and quantity multiplier for calculation
        self._price_multiplier = Decimal(min_price_tick_size) / Decimal(min_display_price_tick_size)
        self._quantity_multiplier = Decimal(min_quantity_tick_size) / Decimal(min_display_quantity_tick_size)

    async def _get_address(self) -> None:
        """
        Get eth chain account address
        Returns:

        """
        self._eth_chain_addr = await self._pub_key.to_address().async_init_num_seq(self._network.lcd_endpoint)

    async def _get_account_id(self) -> None:
        """
        Get subaccount_id for trading
        Returns:

        """
        self._acct_id = await self._client.get_subaccount_list(self._inj_chain_addr)
        self._acct_id = self._acct_id.subaccounts[0]

    async def _get_orderbook(self) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
        """
        Snapshot the orderbook data, only keep top of orderbook
        Returns:

        """
        response = await self._client.get_spot_orderbook(market_id=self._market_id)
        # print(response)
        best_ask = Decimal(response.orderbook.sells[0].price)
        best_ask_quantity = Decimal(response.orderbook.sells[0].quantity)
        best_bid = Decimal(response.orderbook.buys[0].price)
        best_bid_quantity = Decimal(response.orderbook.buys[0].quantity)
        return best_ask / self._price_multiplier, best_ask_quantity / self._quantity_multiplier, best_bid / self._price_multiplier, best_bid_quantity / self._quantity_multiplier

    async def _simulate_transaction(self, tx: Transaction) -> Tuple[Optional[int], Optional[List]]:
        """
        Simulate the transaction to get the estimated gas fee and whether the transaction will succeed
        Args:
            tx: Transaction | the msg send to Injective exchange

        Returns:
            sim_res: Simulation response
            success: succeed or not
        """
        # sign on the transaction
        sim_sign_doc = tx.get_sign_doc(self._pub_key)
        sim_sig = self._priv_key.sign(sim_sign_doc.SerializeToString())
        sim_tx_raw_bytes = tx.get_tx_data(sim_sig, self._pub_key)

        # Simulate the transaction
        (sim_res, success) = await self._client.simulate_tx(sim_tx_raw_bytes)
        if not success:
            print("!!! Failed to estimate !!!")
            return None, None
        else:
            sim_res_msg = self._composer.MsgResponses(sim_res.result.data, simulation=True)
            print(f"!!! Succeed: estimated gas {sim_res.gas_info.gas_used}!!!")
            print("Show simulation msg response: ")
            return sim_res.gas_info.gas_used, sim_res_msg


class SmaSpotStrategy(InjectiveSpotStrategy):
    """
    Mean Reversion Strategies: Simple Moving Average strategy
    Read the Instructions on README.MD

    Key parameters:
        interval_in_seconds:
        n_window:
        n_std:
    """
    def __init__(self, configs: ConfigParser):
        super().__init__(configs=configs)

        # read trading parameters from config
        # frequency of trading measured in second
        self._interval_in_second = configs.getint("interval_in_second", 5)
        # number of total looking-back period
        self._n_window = configs.getint('n_window', 12)
        # number of standard deviation in the upper and lower bound
        self._n_std = configs.getfloat("n_std", 0.5)
        # order size
        self._order_size = configs.getfloat("order_size", 0.01)

        # create data manager
        self._data_manager = SmaDataManager(n_window=self._n_window, n_std=Decimal(self._n_std))

    async def _place_mkt_orders(self, worst_price: float, quantity: float, is_buy: bool = True) -> str:
        """
        Place the market order
        Args:
            worst_price: float | The worst execution price
            quantity: float | the size of the order
            is_buy: bool | True for buy; False for sell

        Returns:
            order_hash: str | unique ID of order
        """
        # prepare transaction msg
        msg = self._composer.MsgCreateSpotMarketOrder(
            sender=self._eth_chain_addr.to_acc_bech32(),
            market_id=self._market_id,
            subaccount_id=self._acct_id,
            fee_recipient=self._fee_recipient,
            price=worst_price,
            quantity=quantity,
            is_buy=is_buy
        )

        # build simulated transaction
        tx = (
            Transaction()
            .with_messages(msg)
            .with_sequence(self._eth_chain_addr.get_sequence())
            .with_account_num(self._eth_chain_addr.get_number())
            .with_chain_id(self._network.chain_id)
        )

        gas_used, sim_res_msg = await self._simulate_transaction(tx)
        if gas_used is None:
            gas_limit = 165000
        else:
            gas_limit = gas_used + 15000 # add 15k for gas_fee limit estimation

        # build transaction
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

        # broadcast transaction: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = self._composer.MsgResponses(res.data)
        print("tx response")
        print(res)

    async def _place_limit_orders(self, price: float, quantity: float, is_buy: bool = True):
        """
        Place the market order
        Args:
            price: float | price of the limit order
            quantity: float | the size of the order
            is_buy: Bool | True for buy; False for sell

        Returns:
            order_hash: str | unique ID of the order

        """
        # prepare transaction msg
        msg = self._composer.MsgCreateSpotLimitOrder(
            sender=self._eth_chain_addr.to_acc_bech32(),
            market_id=self._market_id,
            subaccount_id=self._acct_id,
            fee_recipient=self._fee_recipient,
            price=price,
            quantity=quantity,
            is_buy=is_buy
        )

        # build simulated transaction
        tx = (
            Transaction()
                .with_messages(msg)
                .with_sequence(self._eth_chain_addr.get_sequence())
                .with_account_num(self._eth_chain_addr.get_number())
                .with_chain_id(self._network.chain_id)
        )

        gas_used, sim_res_msg = await self._simulate_transaction(tx)
        if gas_used is None:
            gas_limit = 165000
        else:
            gas_limit = gas_used + 15000  # add 15k for gas_fee limit estimation

        # build transaction
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

        # broadcast transaction: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = self._composer.MsgResponses(res.data)
        print("tx response: ")
        print(res)
        order_hash = res_msg[0].order_hash
        return order_hash

    async def _cancel_orders(self, order_hash: str):
        """
        Cancel Limit orders by order_hash

        Args:
            order_hash: str | unique order id

        Returns:

        """
        # prepare transaction msg
        msg = self._composer.MsgCancelSpotOrder(
            sender=self.address.to_acc_bech32(),
            market_id=self._market_id,
            subaccount_id=self.subaccount_id,
            order_hash=order_hash,
        )

        # build simulated transaction
        tx = (
            Transaction()
                .with_messages(msg)
                .with_sequence(self._eth_chain_addr.get_sequence())
                .with_account_num(self._eth_chain_addr.get_number())
                .with_chain_id(self._network.chain_id)
        )
        gas_used, sim_res_msg = await self._simulate_transaction(tx)
        if gas_used is None:
            gas_limit = 165000
        else:
            gas_limit = gas_used + 15000  # add 15k for gas_fee limit estimation

        # build transaction
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

        # broadcast transaction: send_tx_async_mode, send_tx_sync_mode, send_tx_block_mode
        res = await self._client.send_tx_block_mode(tx_raw_bytes)
        res_msg = self._composer.MsgResponses(res.data)
        print("tx response: ")
        print(res)

    async def trading(self):
        while True:
            print(f'============================TIME: {dt.datetime.now()}============================')
            best_ask, best_ask_quantity, best_bid, best_bid_quantity = await self._get_orderbook()
            print(f'Best Bid: {best_bid}, Best Ask: {best_ask}')
            print(f'Best Bid Size: {best_bid_quantity}, Best Ask Size: {best_ask_quantity}')
            if self._data_manager.update(best_bid, best_ask, best_bid_quantity, best_ask_quantity):
                signal = self._data_manager.generate_signal()
                if -1 == signal:
                    print('Signal: Sell')
                    await self._place_mkt_orders((best_bid + best_ask) / 2, self._order_size, is_buy=False)
                elif 1 == signal:
                    print('Signal: Buy')
                    await self._place_mkt_orders((best_bid + best_ask) / 2, self._order_size, is_buy=True)
            else:
                print("Calculating Mean and Standard Deviation......")

            # wait for {interval_in_second} to get next data point
            sleep(self._interval_in_second)

    def start(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.trading())


class EmaApiManager(InjectiveSpotStrategy):
    def __init__(self):
        return NotImplemented


class EwmaApiManager(InjectiveSpotStrategy):
    def __init__(self):
        return NotImplemented


if __name__ == '__main__':
    configs = ConfigParser()
    configs.read(os.path.join(os.path.join(os.path.join(_main_dir, "python-demo"), "config"), "configs.ini"))
    print(configs.sections())
    print(_main_dir)
    inj_manager = SmaSpotStrategy(configs=configs["mean_reversion"], logger=None)
    asyncio.get_event_loop().run_until_complete(inj_manager._place_mkt_orders(17, 0.01))
