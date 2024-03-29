from decimal import Decimal
from math import floor, ceil


def round_to(value: float, target: float) -> float:
    """
    Round price to price tick value.
    """
    value_tmp = Decimal(str(value))
    target_tmp = Decimal(str(target))
    rounded = float(int(round(value_tmp / target_tmp)) * target_tmp)
    return rounded


def floor_to(value: float, target: float) -> float:
    """
    Similar to math.floor function, but to target float number.
    """
    value_tmp = Decimal(str(value))
    target_tmp = Decimal(str(target))
    result = float(int(floor(value_tmp / target_tmp)) * target_tmp)
    return result


def ceil_to(value: float, target: float) -> float:
    """
    Similar to math.ceil function, but to target float number.
    """
    value_tmp = Decimal(str(value))
    target_tmp = Decimal(str(target))
    result = float(int(ceil(value_tmp / target_tmp)) * target_tmp)
    return result


def get_digits(value: float) -> int:
    """
    Get number of digits after decimal point.
    """
    value_str = str(value)

    if "e-" in value_str:
        _, buf = value_str.split("e-")
        return int(buf)
    elif "." in value_str:
        _, buf = value_str.split(".")
        return len(buf)
    else:
        return 0
