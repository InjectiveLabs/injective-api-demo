import signal
import logging
from asyncio import (
    create_task,
    get_event_loop,
)
from utilities import (
    config_check,
    shutdown,
    handle_exception,
    load_ini,
    restart_program,
)
from market_making import PerpMarketMaker

if __name__ == "__main__":

    logFormatter = logging.Formatter(
        "▸ %(asctime)s.%(msecs)03d %(filename)s:%(lineno)d %(levelname)s %(message)s"
    )
    rootLogger = logging.getLogger()

    fileHandler = logging.FileHandler("avellaneda_stoikov_model.log")
    fileHandler.setFormatter(logFormatter)
    rootLogger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

    rootLogger.setLevel(logging.INFO)

    logging.info("start the avellaneda stoikov bot")

    configs = load_ini("./configs.ini")

    # check config
    config_check(configs)

    loop = get_event_loop()

    perp_market_maker = PerpMarketMaker(
        avellanda_stoikov_configs=configs["AVELLANDA_STOIKOV"],
    )
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: create_task(shutdown(loop, s)))

    try:
        loop.create_task(
            perp_market_maker.market_making_strategy(), name="market_making_strategy"
        )
        loop.run_forever()
    finally:
        loop.run_until_complete(perp_market_maker.close())
        loop.close()
        logging.info("Bye!\n")
        logging.warning("Restarting the program")
        restart_program()
