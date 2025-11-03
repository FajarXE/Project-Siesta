# [GANTI FILE: bot/tgclient.py]

from config import Config

from pyrogram import Client
from async_pymongo import AsyncClient

from .logger import LOGGER
from .settings import bot_set

# Impor Qobuz (menghapus duplikat)
from bot import BOT_QOBUZ_CLIENTS 

# --- MODIFIKASI: Impor manajer Deezer untuk shutdown ---
from .helpers.deezer.manager import deezer_manager
# --- BATAS MODIFIKASI ---

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
        # --- MODIFIKASI: SEMUA logika login dihapus dari sini ---
        # Logika login (Qobuz, Deezer, Tidal, initialize_users)
        # sekarang semuanya ditangani di __main__.py SEBELUM aio.start() dipanggil.
        # --- BATAS MODIFIKASI ---
        LOGGER.info("BOT : Started Successfully")

    async def stop(self, block=False):
        await super().stop(block)
        
        # Tutup klien Tidal (dari bot_set.clients)
        for client in bot_set.clients:
            if hasattr(client, 'session') and client.session:
                await client.session.close()
        
        # Tutup semua klien Qobuz
        for client in BOT_QOBUZ_CLIENTS.values():
            await client.close_session() 
            
        # --- MODIFIKASI: Gunakan deezer_manager untuk menutup sesi Deezer ---
        for client in deezer_manager.clients:
            if client.session and not client.session.closed:
                await client.session.close()
        # --- BATAS MODIFIKASI ---
            
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
