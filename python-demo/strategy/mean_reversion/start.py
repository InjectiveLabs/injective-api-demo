import os
import traceback

# from apscheduler.schedulers.asyncio import AsyncIOScheduler

from mean_reversion_strategy import SmaSpotStrategy
from configparser import ConfigParser

_current_dir = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    # set directories
    main_dir = os.path.dirname(os.path.dirname(_current_dir))
    config_dir = os.path.join(main_dir, 'config')

    # read config files
    config_name = "configs.ini"

    configs = ConfigParser()
    configs.read(os.path.join(config_dir, config_name))
    # print(configs.sections())

    try:
        mean_reversion_demo = SmaSpotStrategy(configs=configs['mean_reversion'])
        mean_reversion_demo.start()
    except Exception as e:
        traceback.extract_tb(e)