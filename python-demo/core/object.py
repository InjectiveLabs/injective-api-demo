from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class TickData(object):
    def __init__(self):
        self.bid_price_1 = 0.0
        self.bid_price_2 = 0.0
        self.bid_price_3 = 0.0
        self.bid_price_4 = 0.0
        self.bid_price_5 = 0.0

        self.ask_price_1 = 0.0
        self.ask_price_2 = 0.0
        self.ask_price_3 = 0.0
        self.ask_price_4 = 0.0
        self.ask_price_5 = 0.0

        self.bid_volume_1 = 0.0
        self.bid_volume_2 = 0.0
        self.bid_volume_3 = 0.0
        self.bid_volume_4 = 0.0
        self.bid_volume_5 = 0.0

        self.ask_volume_1 = 0.0
        self.ask_volume_2 = 0.0
        self.ask_volume_3 = 0.0
        self.ask_volume_4 = 0.0
        self.ask_volume_5 = 0.0

        self.timestamp = 0


@dataclass
class OrderData(object):
    def __init__(self):
        self.order_hash: Optional[str] = None
        self.order_side: Optional[str] = None
        self.market_id: Optional[str] = None
        self.subaccount_id: Optional[str] = None
        self.margin: Optional[float] = None
        self.price = 0.0
        self.quantity = 0.0
        self.unfilled_quantity = 0.0
        self.trigger_price = 0.0
        self.state: Optional[str] = None
        self.created_time = 0
        self.leverage = 1


@dataclass
class TradeData(object):
    def __init__(self):
        self.order_hash = ""
        self.subaccount_id = ""
        self.market_id = ""
        self.trade_execution_type = ""
        self.execution_price = 0.0
        self.execution_quantity = 0.0
        self.trade_direction = ""
        self.execution_margin = 0.0
        self.executed_time = 0
        self.curr_time: Optional[datetime] = None


@dataclass
class PositionData(object):
    def __init__(self):
        self.ticker = ""
        self.subaccount_id = ""
        self.market_id = ""
        self.direction = ""
        self.quantity = 0.0
        self.entry_price = 0.0
        self.margin = 0.0
        self.liquidation_price = 0.0
        self.mark_price = 0.0
        self.aggregate_reduce_only_quantity = 0.0
        self.timestamp = 0


@dataclass
class BarData(object):
    def __init__(self, interval, open, high, low, close, timestamp):
        self.interval = interval
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.timestamp = timestamp
