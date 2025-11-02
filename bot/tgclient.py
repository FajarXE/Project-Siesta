from config import Config

from pyrogram import Client
from async_pymongo import AsyncClient

from .logger import LOGGER
from .settings import bot_set

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
        await bot_set.login_qobuz()
        await bot_set.login_deezer()
        await bot_set.login_tidal()
        await bot_set.initialize_users()
        await bot_set.beatport_initialise()
        LOGGER.info("BOT : Started Successfully")

    async def stop(self, block=False):
        await super().stop(block)
        for client in bot_set.clients:
            await client.session.close()
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
