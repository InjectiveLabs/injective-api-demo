from typing import Tuple
from math import log


def avellaneda_stoikov_model(
    sigma: float,
    mid_price: float,
    limit_horizon: bool,
    quantity: float,
    quantity_max: float = 10,
    kappa: float = 1.5,
    gamma: float = 0.1,
    dt: float = 3.0,
    T: int = 600,  # 10 minutes
) -> Tuple[float, float]:

    # ###############
    # # Option A: Limit time horizon
    if limit_horizon:

        # Reserve price
        reservation_price = mid_price - quantity * gamma * sigma**2 * (T - dt)

        # Reserve spread
        reserve_spread = 2 / gamma * log(1 + gamma / kappa)

        # optimal quotes
        reservation_price_ask = reservation_price + reserve_spread / 2
        reservation_price_bid = reservation_price - reserve_spread / 2

    ###############
    # Option B: Unlimit time horizon
    else:

        # Upper bound of inventory position
        w = 0.5 * gamma**2 * sigma**2 * (quantity_max + 1) ** 2

        # Optimal quotes
        coef = (
            gamma**2 * sigma**2 / (2 * w - gamma**2 * sigma**2 * quantity**2)
        )

        reservation_price_ask = mid_price + log(1 + (1 - 2 * quantity) * coef) / gamma
        reservation_price_bid = mid_price + log(1 + (-1 - 2 * quantity) * coef) / gamma

        # Reserve price
        # reservation_price = (reservation_price_ask + reservation_price_bid) / 2

    return reservation_price_ask, reservation_price_bid
