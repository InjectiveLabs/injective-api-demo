import json
import logging
import os
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from strategy.perp_simple_strategy import Demo
from util.misc import restart_program

_current_dir = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
        datefmt='%Y-%m-%d %A %H:%M:%S',
        filename="./log/demo_log.log",
        filemode='a'
    )

    console = logging.StreamHandler()
    # you can adjust logger level
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s  %(filename)s : %(levelname)s  %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)
    logging.getLogger('apscheduler.executors.default').setLevel(
        logging.WARNING)

    config_path = os.path.join(
        _current_dir, "config", "market_making_setting.json")
    with open(config_path, "r") as file:
        config_dict = json.load(file)
    try:
        Demo(config_dict, logging)
    except Exception as e:
        logging.CRITICAL(traceback.format_exc())
        logging.info("restarting program...")
        restart_program()
