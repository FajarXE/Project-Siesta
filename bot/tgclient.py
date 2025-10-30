from config import Config

from pyrogram import Client
from async_pymongo import AsyncClient

from .logger import LOGGER
from .settings import bot_set

# --- MODIFIKASI DIMULAI ---
# Impor dictionary klien Qobuz yang aktif
from bot import BOT_QOBUZ_CLIENTS
# --- MODIFIKASI SELESAI ---

plugins = dict(
    root="bot/modules"
)

class Bot(Client):
    def __init__(self):
        super().__init__(
            name=Config.BOT_USERNAME,
            api_id=Config.APP_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.TG_BOT_TOKEN,
            plugins=plugins,
            workdir=Config.WORK_DIR,
            workers=100,
            mongodb=dict(connection=AsyncClient(Config.DATABASE_URL), remove_peers=True)
        )

    async def start(self):
        await super().start()
        # await bot_set.login_qobuz() # Dihapus (sudah benar)
        await bot_set.login_deezer()
        await bot_set.login_tidal()
        await bot_set.initialize_users()
        LOGGER.info("BOT : Started Successfully")

    async def stop(self, block=False):
        await super().stop(block)
        
        # --- MODIFIKASI DIMULAI ---
        # Tutup klien Deezer & Tidal
        for client in bot_set.clients:
            if hasattr(client, 'session') and client.session:
                await client.session.close()
        
        # Tutup semua klien Qobuz
        for client in BOT_QOBUZ_CLIENTS.values():
            # Kita gunakan fungsi close_session yang kita buat di qopy.py
            await client.close_session() 
        # --- MODIFIKASI SELESAI ---
            
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
