import os
import signal
import asyncio
import sys
import logging
import traceback
import glob

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
    # Enhanced session file cleanup
    session_patterns = [
        "*.session",
        "aiobot.session",
        f"{Config.BOT_USERNAME}.session",
        f"{Config.WORK_DIR}/*.session",
        f"{Config.WORK_DIR}/aiobot.session",
        f"{Config.WORK_DIR}/{Config.BOT_USERNAME}.session"
    ]
    
    for pattern in session_patterns:
        for session_file in glob.glob(pattern):
            try:
                os.remove(session_file)
                logging.info(f"Removed session file: {session_file}")
            except Exception as e:
                logging.warning(f"Could not remove {session_file}: {e}")

    await bot_set.set_language()
    await aio.start()
    signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    # Create necessary directories
    directories = [
        Config.DOWNLOAD_BASE_DIR,
        Config.WORK_DIR,
        'bot/helpers/OrpheusDL/Download',
        'downloads',
        'tmp'
    ]
    
    for directory in directories:
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
    
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except Exception:
        logging.error(traceback.format_exc())
        sys.exit(1)
