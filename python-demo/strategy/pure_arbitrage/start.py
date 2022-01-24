
import importlib.resources as pkg_resources
import logging
import os
import sys
import traceback
from configparser import ConfigParser
import pyinjective

denoms_testnet = pkg_resources.read_text(pyinjective, 'denoms_testnet.ini')

denoms_mainnet = pkg_resources.read_text(pyinjective, 'denoms_mainnet.ini')

_current_dir = os.path.dirname(os.path.abspath(__file__))
MAIN_DIR = os.path.dirname(os.path.dirname(_current_dir))
CONFIG_DIR = os.path.join(MAIN_DIR, 'config')
sys.path.insert(0, MAIN_DIR)


if __name__ == "__main__":
    from util.misc import restart_program
    from perp_arbitrage import Demo

    log_dir = "./log"
    log_name = "./pure_arb_demo.log"
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
    mainnet_configs.read_string(denoms_mainnet)
    testnet_configs = ConfigParser()
    testnet_configs.read_string(denoms_testnet)

    try:
        perp_demo = Demo(
            configs['pure arbitrage'], logging, mainnet_configs, testnet_configs)
        perp_demo.start()
    except Exception as e:
        logging.CRITICAL(traceback.format_exc())
        logging.info("restarting program...")
        restart_program()
