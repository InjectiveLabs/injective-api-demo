
import json
import logging
import os
import pdb
import sys
import traceback
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from configparser import ConfigParser

_current_dir = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.dirname(os.path.dirname(_current_dir))
CONFIG_DIR = os.path.join(MAIN_DIR, 'config')
sys.path.insert(0, MAIN_DIR)


if __name__ == "__main__":
    from util.misc import restart_program
    from perp_simple_strategy import Demo

    log_dir = "./log"
    log_name = "./perp_demo.log"
    config_name = "configs.ini"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
        datefmt='%Y-%m-%d %A %H:%M:%S',
        filename=os.path.join(log_dir, log_name),
        filemode='a'
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s  %(filename)s : %(levelname)s  %(message)s')
    console.setFormatter(formatter)
    logging.getLogger().addHandler(console)
    logging.getLogger('apscheduler.executors.default').setLevel(
        logging.WARNING)

    configs = ConfigParser()
    configs.read(os.path.join(CONFIG_DIR, config_name))
    mainnet_configs = ConfigParser()
    mainnet_configs.read(os.path.join(CONFIG_DIR, "denoms_mainnet.ini"))
    testnet_configs = ConfigParser()

    testnet_configs.read(os.path.join(CONFIG_DIR, "denoms_testnet.ini"))

    try:
        perp_demo = Demo(
            configs['pure perp market making'], logging, mainnet_configs, testnet_configs)
        perp_demo.start()
    except Exception as e:
        logging.CRITICAL(traceback.format_exc())
        logging.info("restarting program...")
        restart_program()
