import json
import logging
import os
import traceback

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from strategy.perp_simple_strategy import Demo
from util.misc import restart_program

_current_dir = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    log_dir = "./log"
    log_name = "./perp_demo.log"
    config_name = "market_making_setting.json"
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
        datefmt='%Y-%m-%d %A %H:%M:%S',
        filename=os.path.join(log_dir, log_name),
        filemode='a'
    )
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
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
        _current_dir, "config", config_name)
    with open(config_path, "r") as file:
        config_dict = json.load(file)
    try:
        perp_demo = Demo(config_dict, logging)
        perp_demo.start()
    except Exception as e:
        logging.CRITICAL(traceback.format_exc())
        logging.info("restarting program...")
        restart_program()
