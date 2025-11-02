import os
import signal
import asyncio
import sys
import logging
import traceback

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
    # Clean any existing session files to prevent AuthKeyDuplicated error
    session_files = [
        "aiobot.session",
        f"{Config.BOT_USERNAME}.session",
        f"{Config.WORK_DIR}/aiobot.session",
        f"{Config.WORK_DIR}/{Config.BOT_USERNAME}.session"
    ]
    
    for session_file in session_files:
        if os.path.exists(session_file):
            try:
                os.remove(session_file)
                logging.info(f"Removed session file: {session_file}")
            except Exception as e:
                logging.warning(f"Could not remove {session_file}: {e}")

    await bot_set.set_language()
    await aio.start()
    signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    
    # Ensure work directory exists
    if Config.WORK_DIR and not os.path.isdir(Config.WORK_DIR):
        os.makedirs(Config.WORK_DIR)
    
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except Exception:
        logging.error(traceback.format_exc())
        sys.exit(1)