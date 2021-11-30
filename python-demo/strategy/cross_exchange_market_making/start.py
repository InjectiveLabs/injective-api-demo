import os
from configparser import ConfigParser
from cross_exchange_market_making_batch import run_cross_exchange_market_making

_current_dir = os.path.abspath(__file__)


if __name__ == "__main__":
    config_dir = os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_current_dir))),'config'),'configs.ini')

    config = ConfigParser()
    config.read(config_dir)
    print(config.sections())
    cross_exchange_market_making_config = config["cross_exchange_market_making"]
    run_cross_exchange_market_making(cross_exchange_market_making_config)