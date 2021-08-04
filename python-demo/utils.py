from decimal import Decimal


def get_price_string(price, base_decimals, quote_decimals, precision=18) -> str:
    scale = Decimal(quote_decimals - base_decimals)
    exchange_price = Decimal(price) * pow(10, scale)
    price_string = ("{:."+str(precision)+"f}").format(exchange_price)
    print("price string :{}".format(price_string))
    return price_string

def get_quantity_string(quantity, base_decimals, precision=18) -> str:
    scale = Decimal(base_decimals)
    exchange_quantity = Decimal(quantity) * pow(10, scale)
    quantity_string = ("{:."+str(precision)+"f}").format(exchange_quantity)
    print("quantity string:{}".format(quantity_string))
    return quantity_string

# test
if __name__ == "__main__":
    assert "0.000000005000000000"==get_price_string(5000, 18, 6, 18), "result of get_price is wrong."
    assert "1222000000000000000000.000000000000000000" == get_quantity_string(1222, 18, 18), "result of get_quantity is wrong."
