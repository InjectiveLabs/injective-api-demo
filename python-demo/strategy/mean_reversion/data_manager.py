from abc import (ABC, abstractmethod)
from collections import deque

import numpy as np


class DataManager(ABC):
    """
    Data Manager

    used to manipulate data and generate signals
    """
    def __init__(self, n_win, n_std, **kwargs):
        """

        Args:
            n_win: Decimal | the number of period in the moving window
            n_std: Decimal | the number of standard deviation in the upper anad lower bound
            **kwargs:
        """
        self.n_win = n_win
        self.n_std = n_std

        self.container = dict()
        self.container['BestBid'] = deque([0], maxlen=self.n_win)
        self.container['BestAsk'] = deque([0], maxlen=self.n_win)
        self.container['BestBidQuantity'] = deque([0], maxlen=self.n_win)
        self.container['BestAskQuantity'] = deque([0], maxlen=self.n_win)
        self.container['MidPrice'] = deque([0], maxlen=self.n_win)
        self.container['AVG'] = deque([0], maxlen=self.n_win)
        self.container['STD'] = deque([0], maxlen=self.n_win)
        self.container['Upper'] = deque([0], maxlen=self.n_win)
        self.container['Lower'] = deque([0], maxlen=self.n_win)

    @abstractmethod
    def update(self):
        pass

    @abstractmethod
    def generate_signal(self):
        pass


class SmaDataManager(DataManager):
    def __init__(self, n_window=20, n_std=2, **kwargs):
        super().__init__(n_win=n_window, n_std=n_std, **kwargs)

    def _add(self, best_bid, best_ask, best_bid_quantity, best_ask_quantity):
        """
        Accumulate data point to calculate moving average and moving standard deviation in the starting phase

        Args:
            best_bid:
            best_ask:
            best_bid_quantity:
            best_ask_quantity:

        Returns:

        """
        # calculate mid price
        mid_price = (best_bid + best_ask) / 2
        # add top of orderbook and quantity to the data container
        self.container['BestBid'].append(best_bid)
        self.container['BestAsk'].append(best_ask)
        self.container['BestBidQuantity'].append(best_bid_quantity)
        self.container['BestAskQuantity'].append(best_ask_quantity)
        self.container['MidPrice'].append(mid_price)

        # calculate the moving average and moving standard deviation
        self.container['AVG'].append(self.container['AVG'][-1] + mid_price / self.n_win)
        self.container['STD'].append(0)

        # calculate the upper band and the lower band
        self.container['Upper'].append(0)
        self.container['Lower'].append(0)

    def _replace(self, best_bid, best_ask, best_bid_quantity, best_ask_quantity):
        """
        Moving the sliding window and get the latest moving mean and moving standard deviation
        Args:
            best_bid:
            best_ask:
            best_bid_quantity:
            best_ask_quantity:

        Returns:

        """
        # calculate mid price
        mid_price = (best_bid + best_ask) / 2

        # add top of orderbook and quantity to the data container
        self.container['BestBid'].append(best_bid)
        self.container['BestAsk'].append(best_ask)
        self.container['BestBidQuantity'].append(best_bid_quantity)
        self.container['BestAskQuantity'].append(best_ask_quantity)

        # calculate the moving average and moving standard deviation
        self.container['AVG'].append(self.container['AVG'][-1] - (self.container['MidPrice'][0] / self.n_win) +
                                     (mid_price / self.n_win))
        self.container['MidPrice'].append(mid_price)
        std = np.std(self.container["MidPrice"])

        # calculate the upper band and the lower band
        self.container['STD'].append(std)
        self.container['Upper'].append(mid_price + self.n_std * std)
        self.container['Lower'].append(mid_price - self.n_std * std)

    def update(self, best_bid, best_ask, best_bid_quantity, best_ask_quantity):
        """
        Feed the latest top of orderbook data to data container

        Args:
            best_bid:
            best_ask:
            best_bid_quantity:
            best_ask_quantity:

        Returns:

        """
        if self.container['MidPrice'][0]:
            self._replace(best_bid, best_ask, best_bid_quantity, best_ask_quantity)
            return True
        else:
            self._add(best_bid, best_ask, best_bid_quantity, best_ask_quantity)
            return False

    def generate_signal(self):
        """
        Building rules to calculate real-time trading signal

        Returns:
            -1 ==> sell
            1  ==> buy
            0  ==> hold

        """
        if self.container["AVG"][-2] < self.container['MidPrice'][-2] < self.container['Upper'][-2]:
            if self.container['MidPrice'][-1] > self.container['Upper'][-1]:
                return -1
            elif self.container['MidPrice'][-1] < self.container['AVG'][-1]:
                return 1
            else:
                return 0
        if self.container["AVG"][-2] > self.container['MidPrice'][-2] > self.container['Lower'][-2]:
            if self.container['MidPrice'][-1] < self.container['Lower'][-1]:
                return 1
            elif self.container['MidPrice'][-1] > self.container["AVG"][-1]:
                return -1
            else:
                return 0
        else:
            return 0


class EmaDataManager(DataManager):
    def __init__(self, n_window=20, maxlen=100, **kwargs):
        super().__init__(n_win=n_window, maxlen=maxlen, **kwargs)
        self.smoothing = kwargs.get('smoothing', 3)
        self.smoothing_adj = self.smoothing/(1 + self.n_win)
        self.smoothing_adj_1 = 1 - self.smoothing_adj


class EwmaDataManager(DataManager):
    def __init__(self, n_window=20, maxlen=100, **kwargs):
        super().__init__(n_win=20, maxlen=100, **kwargs)
        self.alpha = kwargs.get('alpha', 0.4)
        self.alpha_1 = 1 - self.alpha


