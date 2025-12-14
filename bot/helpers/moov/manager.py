import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from .mvapi import MoovAPI

# Dummy database fallback
try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
    database = DummyDatabase()

class MoovLoginManager:
    def __init__(self):
        self.clients = []
        self._client_cycler = None
        self.quality = "FLAC" 
        self.user_data = {}

    async def initialize_clients(self):
        # Ambil akun dari Config. Format di Config.py nanti:
        # MOOV_ACCOUNTS = [{"email": "...", "password": "...", "proxy": "http://user:pass@host:port"}]
        accounts = getattr(Config, 'MOOV_ACCOUNTS', [])
        
        if not accounts:
            LOGGER.warning("Moov Manager: Tidak ada akun (MOOV_ACCOUNTS) di Config.")
            return

        LOGGER.info(f"Moov Manager: Menginisialisasi {len(accounts)} akun...")
        tasks = []
        for account in accounts:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        self.clients = [c for c in results if c is not None]
        
        if not self.clients:
            LOGGER.error("Moov Manager: Gagal login ke SEMUA akun Moov.")
            return

        LOGGER.info(f"Moov Manager: Berhasil login {len(self.clients)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account):
        # Pass proxy dari config ke API
        client = MoovAPI(proxy=account.get('proxy'))
        try:
            success = await client.login(account['email'], account['password'])
            if success:
                LOGGER.info(f"Moov Manager: Login OK - {account['email']}")
                return client
            else:
                LOGGER.error(f"Moov Manager: Login Gagal - {account['email']}")
                await client.close()
                return None
        except Exception as e:
            LOGGER.error(f"Moov Manager: Exception {account.get('email')}: {e}")
            await client.close()
            return None

    def get_client(self) -> MoovAPI | None:
        if not self._client_cycler:
            return None
        try:
            return next(self._client_cycler)
        except StopIteration:
            return None

    async def setup_quality(self, user_id: int, qual: str):
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["FLAC", "MP3_320"]: # Moov hanya punya HiRes/Lossless (FLAC) dan Lossy
            self.user_data[user_id]['moov_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('moov_qual', self.quality)

    async def shutdown(self):
        for c in self.clients:
            await c.close()

moov_manager = MoovLoginManager()
