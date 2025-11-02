import os
import signal
import asyncio, sys, logging, traceback
import socket
import subprocess

from bot import Config

from .tgclient import aio
from .settings import bot_set
from .logger import LOGGER

def signal_handler(s, f):
    try:
        logging.info("Signal received! Exiting....")
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)


async def main():
    # Enhanced startup diagnostics
    hostname = socket.gethostname()
    
    # Try to get container ID if running in Docker
    container_id = "unknown"
    try:
        with open('/proc/self/cgroup', 'r') as f:
            for line in f:
                if 'docker' in line or 'containerd' in line:
                    container_id = line.split('/')[-1].strip()[:12]
                    break
    except:
        try:
            container_id = os.environ.get('HOSTNAME', 'unknown')[:12]
        except:
            pass
    
    # Try to get git commit info
    git_commit = "unknown"
    try:
        git_commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], 
                                          cwd='/home/engine/project', 
                                          stderr=subprocess.DEVNULL).decode().strip()
    except:
        pass
    
    LOGGER.info("=".join(["="] * 60))
    LOGGER.info("BOT : PROJECT-SIESTA STARTING UP")
    LOGGER.info("=".join(["="] * 60))
    LOGGER.info(f"BOT : Deployment diagnostics:")
    LOGGER.info(f"BOT : - Hostname: {hostname}")
    LOGGER.info(f"BOT : - Container ID: {container_id}")
    LOGGER.info(f"BOT : - Git commit: {git_commit}")
    LOGGER.info(f"BOT : - Session name: {Config.SESSION_NAME}")
    LOGGER.info(f"BOT : - Session directory: {Config.SESSION_DIR}")
    LOGGER.info(f"BOT : - Bot username: {Config.BOT_USERNAME}")
    LOGGER.info(f"BOT : - Work directory: {Config.WORK_DIR}")
    
    # Ensure session directory exists and is writable
    try:
        os.makedirs(Config.SESSION_DIR, exist_ok=True)
        test_file = os.path.join(Config.SESSION_DIR, '.test_write')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        LOGGER.info(f"BOT : Session directory {Config.SESSION_DIR} is writable")
    except Exception as e:
        LOGGER.error(f"BOT : Cannot write to session directory {Config.SESSION_DIR}: {e}")
        sys.exit(1)
    
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
