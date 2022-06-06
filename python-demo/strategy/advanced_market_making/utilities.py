import logging
from typing import Tuple, List
from pyinjective.constant import Network
from pyinjective.composer import Composer
from pyinjective.async_client import AsyncClient
from asyncio import (
    create_task,
    all_tasks,
    current_task,
    gather,
    sleep,
    Task,
    CancelledError,
)
import aiohttp
from configparser import ConfigParser
import signal
import sys
import os


async def shutdown(loop, signal=None):
    if signal:
        logging.info(f"Received exit signal {signal.name}...")
    tasks = [task for task in all_tasks() if task is not current_task()]

    for task in tasks:
        task.cancel()

    logging.info(f"Cancelling {len(tasks)} outstanding tasks")
    res = await gather(*tasks, return_exceptions=True)
    logging.info(f"Cancelled {len(tasks)} outstanding tasks {res}")
    loop.stop()


def handle_exception(loop, context):
    logging.error(f"Exception full context: {context}")
    msg = context.get("exception", context["message"])
    logging.error(f"Caught exception: {msg}")
    logging.info("Shutting down...")
    # This won't cancel all orders
    exception_caused_shutdown = create_task(
        shutdown(loop, signal=signal.SIGINT), name="shutdown from handle_exception"
    )


def load_ini(ini_filename: str):
    """
    Load data from ini file, including path
    """
    try:
        config = ConfigParser()
        config.read(ini_filename)
        return config
    except IOError:
        raise IOError(f"Failed to open/find {ini_filename}")


# Checking this specia error and restart the program
async def server_check():
    """
    Check if the server is running
    """
    # TODO check the server i'm using, and all the backup servers

    for sentry in ["sentry0", "sentry1", "sentry3"]:
        url = f"{sentry}.injective.network:26657/status"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    if res["result"]["sync_info"]["catching_up"]:
                        for sentry in ["sentry0", "sentry1", "sentry3"]:
                            url = f"{sentry}.injective.network:26657/status"
                            async with session.get(url) as resp:
                                if resp.status == 200:
                                    res = await resp.json()
                                    if not res["result"]["sync_info"]["catching_up"]:
                                        _node = sentry
                                        raise Exception(f"Change node to {_node}")
                    else:
                        pass


def _handle_task_result(task: Task) -> None:
    try:
        task.result()
    except CancelledError:
        pass  # Task cancellation should not be logged as an error.
    except Exception:  # pylint: disable=broad-except
        logging.exception("Exception raised by task = %r", task)

        raise Exception(f"Task {task.get_name()} failed, {task.exception()}")


def restart_program():
    python = sys.executable
    os.execl(python, python, *sys.argv)


def round_down(number: float, decimals: int) -> float:
    v = int(number * (10**decimals)) / 10**decimals
    if v < 0.0001:
        return 0.0001
    return v


def truncate_float(number: float, decimals: int) -> float:
    return int(number * (10**decimals)) / 10**decimals


def switch_network(
    nodes: List[str], index: int, is_mainnet: bool = False
) -> Tuple[int, Network, bool]:
    n = index % len(nodes)

    if is_mainnet:
        if nodes[n] == "k8s":
            is_insecure = False
        else:
            is_insecure = True
        network = Network.mainnet(nodes[n])
    else:
        is_insecure = False
        network = Network.testnet()
    return n, network, is_insecure


def update_composer(network: str) -> Composer:
    return Composer(network=network)


def build_client(network: Network, is_insecure: bool) -> AsyncClient:
    return AsyncClient(network=network, insecure=is_insecure)


def build_client_and_composer(
    network: Network, is_insecure: bool
) -> Tuple[AsyncClient, Composer]:
    return build_client(network, is_insecure), update_composer(network.string())


def config_check(config):
    """
    check if config file is valid
    """

    def range_check(section_name, value, lower_bound, upper_bound):
        if (value >= lower_bound) and (value <= upper_bound):
            logging.info(f"{section_name}: {value}")
        elif value < lower_bound:
            raise Exception(
                f"{section_name} must be greater than {lower_bound}, got {value}"
            )
        else:
            raise Exception(
                f"{section_name} must be less than {upper_bound}, got {value}"
            )

    range_check(
        "update_interval",
        config["AVELLANDA_STOIKOV"].getint("update_interval"),
        1,
        6000,
    )
    range_check("n_orders", config["AVELLANDA_STOIKOV"].getint("n_orders"), 1, 19)
    range_check(
        "first_order_delta",
        config["AVELLANDA_STOIKOV"].getfloat("first_order_delta"),
        0,
        0.20,
    )
    range_check(
        "last_order_delta",
        config["AVELLANDA_STOIKOV"].getfloat("last_order_delta"),
        0.01,
        0.03,
    )
    range_check(
        "ask_total_asset_allocation",
        config["AVELLANDA_STOIKOV"].getfloat("ask_total_asset_allocation"),
        0.05,
        0.60,
    )
    range_check(
        "bid_total_asset_allocation",
        config["AVELLANDA_STOIKOV"].getfloat("bid_total_asset_allocation"),
        0.05,
        0.60,
    )
    range_check(
        "first_asset_allocation",
        config["AVELLANDA_STOIKOV"].getfloat("first_asset_allocation"),
        0,
        0.05,
    )
    range_check(
        "last_asset_allocation",
        config["AVELLANDA_STOIKOV"].getfloat("last_asset_allocation"),
        0.9,
        1.2,
    )
