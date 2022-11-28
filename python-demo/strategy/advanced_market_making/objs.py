from enum import Enum, unique
from configparser import ConfigParser
import importlib.resources as pkg_resources
import pyinjective
from pyinjective.constant import Denom
from pyinjective.constant import Network


class Market:
    def __init__(self, base: str, quote: str, is_mainnet: bool):
        self.base_ticker = f"w{base}" if base in ["btc", "eth"] else base
        self.quote_ticker = quote

        ini_config_dir = pkg_resources.read_text(
            pyinjective, "denoms_mainnet.ini" if is_mainnet else "denoms_testnet.ini"
        )
        # read denoms configs
        self.config = ConfigParser()
        self.config.read_string(ini_config_dir)


class MarketDerivative(Market):
    def __init__(self, base: str, quote: str, network: Network, is_mainnet: bool):
        super().__init__(base, quote, is_mainnet)

        self.quote_peggy, self.quote_decimals = Denom.load_peggy_denom(
            network, self.quote_ticker.upper()
        )
        self.quote_multiplier = pow(10, self.quote_decimals)

        for section in self.config.sections():
            if len(section) == 66:
                if (
                    f"{self.base_ticker.upper()}/{self.quote_ticker.upper()}"
                    in self.config.get(section, "description")
                    and "Derivative" in self.config.get(section, "description")
                    and "PERP" in self.config.get(section, "description")
                ):
                    self.market_id = section

                    self.market_denom = Denom.load_market(network.env, self.market_id)
                    
class MarketDerivativeFutures(Market):
    def __init__(self, base: str, quote: str, network: Network, is_mainnet: bool):
        super().__init__(base, quote, is_mainnet)

        self.quote_peggy, self.quote_decimals = Denom.load_peggy_denom(
            network, self.quote_ticker.upper()
        )
        self.quote_multiplier = pow(10, self.quote_decimals)

        for section in self.config.sections():
            if len(section) == 66:
                if (
                    f"{self.base_ticker.upper()}/{self.quote_ticker.upper()}"
                    in self.config.get(section, "description")
                    and "Derivative" in self.config.get(section, "description")
                    and not "PERP" in self.config.get(section, "description")
                ):
                    self.market_id = section

                    self.market_denom = Denom.load_market(network.env, self.market_id)


class MarketSpot(MarketDerivative):
    def __init__(self, base: str, quote: str, network: Network, is_mainnet: bool):
        super().__init__(base, quote, network, is_mainnet)
        if self.base_ticker in ["wbtc", "weth"]:
            self.base_ticker = self.base_ticker[1:]

        self.base_peggy, self.base_decimals = Denom.load_peggy_denom(
            network, self.base_ticker.upper()
        )
        self.base_multiplier = pow(10, self.base_decimals)

        for section in self.config.sections():
            if len(section) == 66:
                if (
                    f"{self.base_ticker.upper()}/{self.quote_ticker.upper()}"
                    in self.config.get(section, "description")
                    and "Spot" in self.config.get(section, "description")
                ):
                    self.market_id = section

                    self.market_denom = Denom.load_market(network.env, self.market_id)


class Spread:
    def __init__(
        self, lower_bound: float = 10, upper_bound: float = 200, spread: float = 18
    ):
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.spread = spread

    def update(self, delta: float):
        if self.spread < self.upper_bound or self.spread > self.lower_bound:
            self.spread += delta
            print(f"current spread: {self.spread}")
        else:
            print(f"Spread is at the boundary {self.spread}")


class PositionDerivative:
    def __init__(self):
        self.direction = ""
        self.net_quantity = 0.0
        self.entry_price = 0.0
        self.margin = 0.0
        self.liquidation_price = 0.0
        self.mark_price = 0.0
        self.aggregate_reduce_only_quantity = 0.0
        self.timestamp = 0
        self.residual_reduce_only_quantity = 0.0

    def update(
        self,
        direction: str,
        quantity: float,
        entry_price: float,
        margin: float,
        liquidation_price: float,
        mark_price: float,
        aggregate_reduce_only_quantity: float,
        timestamp: int,
    ):
        self.direction = direction
        self.net_quantity = quantity
        self.entry_price = entry_price
        self.margin = margin
        self.liquidation_price = liquidation_price
        self.mark_price = mark_price
        self.aggregate_reduce_only_quantity = aggregate_reduce_only_quantity
        self.timestamp = timestamp

    def reset(self):
        self.direction = ""
        self.net_quantity = 0.0
        self.entry_price = 0.0
        self.margin = 0.0
        self.liquidation_price = 0.0
        self.mark_price = 0.0
        self.aggregate_reduce_only_quantity = 0.0
        self.timestamp = 0
        self.residual_reduce_only_quantity = 0.0


class BalanceDerivative:
    def __init__(self, available_balance=100.0, total_balance=100.0):
        self.initial_quote_balance = 0.0
        self.current_quote_balance = 0.0
        self.available_balance = available_balance
        self.total_balance = total_balance

    def update_balance(self, available_balance: float, total_balance: float):
        self.available_balance = available_balance
        self.total_balance = total_balance

    def update_quote(self, quote_balance: float):
        self.current_quote_balance = quote_balance

    def reset_initial_balance(self):
        self.initial_quote_balance = self.current_quote_balance

    def delta(self):
        return self.current_quote_balance - self.initial_quote_balance


class BalanceSpot(BalanceDerivative):
    def __init__(self, available_balance=100.0, total_balance=100.0):
        super().__init__(available_balance, total_balance)
        self.initial_base_balance = 0.0
        self.current_base_balance = 0.0
        self.available_balance = available_balance
        self.total_balance = total_balance

    def update_balance(self, available_balance: float, total_balance: float):
        self.available_balance = available_balance
        self.total_balance = total_balance

    def update_quote(self, quote_balance: float):
        self.current_quote_balance = quote_balance

    def update_base(self, base_balance: float):
        self.current_base_balance = base_balance

    def upate_base_quote(self, base_balance: float, quote_balance: float):
        self.update_base(base_balance)
        self.update_quote(quote_balance)

    def reset_initial_balance(self):
        self.initial_base_balance = self.current_base_balance
        self.initial_quote_balance = self.current_quote_balance

    def delta(self):
        return self.current_quote_balance - self.initial_quote_balance


class OrderDerivative:
    def __init__(self, msg, price, quantity, timestamp, side, order_hash=""):
        self.msg = msg
        self.price = price
        self.quantity = quantity
        self.order_hash = order_hash
        self.timestamp = timestamp
        self.side = side

    def __lt__(self, obj):
        if self.timestamp != 0 and obj.timestamp != 0:
            return self.timestamp < obj.timestamp
        elif self.timestamp == 0 and obj.timestamp == 0:
            if self.side == "buy":
                return self.price > obj.price
            else:
                return self.price <= obj.price
        elif self.timestamp != 0 and obj.timestamp == 0:
            return False
        # elif self.timestamp == 0 and obj.timestamp != 0:
        return True

    def __le__(self, obj):
        if self.timestamp != 0 and obj.timestamp != 0:
            if self.timestamp < obj.timestamp:
                return True
            elif self.timestamp > obj.timestamp:
                return False
            return self.price <= obj.price
        elif self.timestamp == 0 and obj.timestamp == 0:
            return self.price <= obj.price
        elif self.timestamp != 0 and obj.timestamp == 0:
            return False
        return True

    def __gt__(self, obj):
        if self.timestamp != 0 and obj.timestamp != 0:
            if self.timestamp > obj.timestamp:
                return True
            elif self.timestamp < obj.timestamp:
                return False
            else:
                return self.price >= obj.price
        elif self.timestamp == 0 and obj.timestamp == 0:
            return self.price > obj.price
        elif self.timestamp != 0 and obj.timestamp == 0:
            return True
        return False

    def __ge__(self, obj):
        if self.timestamp != 0 and obj.timestamp != 0:
            if self.timestamp > obj.timestamp:
                return True
            return self.price >= obj.price
        elif self.timestamp == 0 and obj.timestamp == 0:
            return self.price >= obj.price
        elif self.timestamp != 0 and obj.timestamp == 0:
            return True
        return False

    def __eq__(self, obj):
        if self.timestamp == obj.timestamp and self.price == obj.price:
            return True
        return False

    def __repr__(self):
        return f"\nOrderDerivative: ts: {self.timestamp}, price: {self.price:4.4f}, quantity: {self.quantity:.4f}, hash: {self.order_hash}\n"


class GammaDerivative:
    def __init__(
        self,
        lb: float = 0.1,
        ub: float = 3.0,
        gamma: float = 0.7,
        leverage: float = 1.0,
    ):
        self.lb = lb
        self.ub = ub
        self.gamma = gamma
        self.leverage = leverage

    def update(self, delta: float):
        if self.gamma < self.ub or self.gamma > self.lb:
            self.gamma += delta
            print(f"current gamma: {self.gamma}")
        else:
            print("Gamma is at the boundary")

    def update_leverage_ratio(self, leverage: float):
        self.leverage = leverage


class NoValue(Enum):
    def __repr__(self):
        return f"{self.__class__.__name__}.{self.name}"


@unique
class Side(NoValue):
    LONG = "long"
    SHORT = "short"
    UNKNOWN = "unknown"
