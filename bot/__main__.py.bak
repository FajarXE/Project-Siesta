import os
import signal
import asyncio, sys, logging, traceback

from bot import Config

from .tgclient import aio
from .settings import bot_set

def signal_handler(s, f):
    try:
        logging.info("Signal received! Exiting....")
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)


async def main():
    await bot_set.set_language()
    await aio.start()
    signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except Exception:
        logging.error(traceback.format_exc())
        sys.exit(1)
    
