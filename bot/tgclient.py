import os
import socket
import asyncio
import sys
from config import Config

from pyrogram import Client
from pyrogram.errors import AuthKeyDuplicated
from async_pymongo import AsyncClient

from .logger import LOGGER
from .settings import bot_set
from .helpers.distributed_lock import DistributedLock

plugins = dict(
    root="bot/modules"
)

class Bot(Client):
    def __init__(self):
        # Ensure session directory exists
        os.makedirs(Config.SESSION_DIR, exist_ok=True)
        
        # Create full session path
        session_path = os.path.join(Config.SESSION_DIR, Config.SESSION_NAME)
        
        # Log startup diagnostics
        hostname = socket.gethostname()
        LOGGER.info(f"BOT : Starting up with diagnostics:")
        LOGGER.info(f"BOT : - Session path: {session_path}")
        LOGGER.info(f"BOT : - Hostname: {hostname}")
        LOGGER.info(f"BOT : - Bot username: {Config.BOT_USERNAME}")
        LOGGER.info(f"BOT : - Work dir: {Config.WORK_DIR}")
        
        # Initialize distributed lock (optional, enabled by default)
        self.use_distributed_lock = os.environ.get('ENABLE_DISTRIBUTED_LOCK', 'true').lower() == 'true'
        self.distributed_lock = None
        self.lock_renewal_task = None
        
        if self.use_distributed_lock:
            self.distributed_lock = DistributedLock(
                lock_key=f"tg_client_{Config.SESSION_NAME}",
                ttl_minutes=int(os.environ.get('LOCK_TTL_MINUTES', '5'))
            )
        
        super().__init__(
            name=session_path,
            api_id=Config.APP_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.TG_BOT_TOKEN,
            plugins=plugins,
            workdir=Config.WORK_DIR,
            workers=100,
            mongodb=dict(connection=AsyncClient(Config.DATABASE_URL), remove_peers=True)
        )

    async def start(self):
        # Try to acquire distributed lock first (if enabled)
        if self.use_distributed_lock and self.distributed_lock:
            LOGGER.info("LOCK : Attempting to acquire distributed lock...")
            lock_acquired = await self.distributed_lock.acquire_lock()
            
            if not lock_acquired:
                LOGGER.error("LOCK : Failed to acquire distributed lock - another instance may be running")
                LOGGER.error("LOCK : To override, set ENABLE_DISTRIBUTED_LOCK=false or use different SESSION_NAME")
                sys.exit(1)
            
            # Start lock renewal task
            self.lock_renewal_task = await self.distributed_lock.start_renewal_task()
            LOGGER.info("LOCK : Distributed lock acquired and renewal task started")
        
        try:
            await super().start()
            await bot_set.login_qobuz()
            await bot_set.login_deezer()
            await bot_set.login_tidal()
            await bot_set.initialize_users()
            await bot_set.beatport_initialise()
            LOGGER.info("BOT : Started Successfully")
        except AuthKeyDuplicated as e:
            session_path = os.path.join(Config.SESSION_DIR, Config.SESSION_NAME)
            LOGGER.error(f"BOT : AUTH_KEY_DUPLICATED - Session conflict detected!")
            LOGGER.error(f"BOT : Session path: {session_path}")
            LOGGER.error(f"BOT : This usually means another instance is running with the same session.")
            LOGGER.error(f"BOT : Solution: Stop the other instance or use a different SESSION_NAME/SESSION_DIR")
            LOGGER.error(f"BOT : Error details: {e}")
            
            # Release distributed lock if we acquired it
            if self.use_distributed_lock and self.distributed_lock:
                await self.distributed_lock.release_lock()
            
            sys.exit(1)
        except Exception as e:
            LOGGER.error(f"BOT : Failed to start: {e}")
            
            # Release distributed lock if we acquired it
            if self.use_distributed_lock and self.distributed_lock:
                await self.distributed_lock.release_lock()
            
            sys.exit(1)

    async def stop(self, block=False):
        await super().stop(block)
        for client in bot_set.clients:
            await client.session.close()
        
        # Cancel lock renewal task and release distributed lock
        if self.use_distributed_lock and self.distributed_lock:
            if self.lock_renewal_task:
                self.lock_renewal_task.cancel()
                try:
                    await self.lock_renewal_task
                except asyncio.CancelledError:
                    pass
            
            await self.distributed_lock.release_lock()
            LOGGER.info("LOCK : Distributed lock released")
        
        LOGGER.info('BOT : Exited Successfully ! Bye..........')

aio = Bot()
