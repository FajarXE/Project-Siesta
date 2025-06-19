import os
import logging
import inspect

log_file_path = "./bot/bot_logs.log"

# Config file has logging so removing that handler 
try:
    logging.getLogger().removeHandler(logging.getLogger().handlers[0])
except:
    pass

logging.basicConfig(
    format="[%(levelname)s] - [%(asctime)s] [%(filename)s:%(lineno)d] %(message)s",
    handlers=[logging.FileHandler(log_file_path), logging.StreamHandler()],
    level=logging.INFO,
)


LOGGER = logging.getLogger(__name__)
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
