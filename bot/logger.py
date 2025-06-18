import os
import logging
import inspect

log_file_path = "./bot/bot_logs.log"

# Config file has logging so removing that handler 
try:
    logging.getLogger().removeHandler(logging.getLogger().handlers[0])
except:
    pass

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.DEBUG)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)
logging.getLogger("Librespot:Session").setLevel(logging.WARNING)
logging.getLogger("Librespot:MercuryClient").setLevel(logging.WARNING)
logging.getLogger("Librespot:TokenProvider").setLevel(logging.WARNING)
logging.getLogger("librespot.audio").setLevel(logging.WARNING)
logging.getLogger("Librespot:ApiClient").setLevel(logging.WARNING)
logging.getLogger("pydub").setLevel(logging.WARNING)
logging.getLogger("spotipy").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.ERROR)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]')

# Create file handler
file_handler = logging.FileHandler(log_file_path, 'a', 'utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)
LOGGER.addHandler(file_handler)

# Create console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)
LOGGER.addHandler(console_handler)