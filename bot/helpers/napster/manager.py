# [BUAT FILE BARU: bot/helpers/napster/manager.py]

import asyncio
import itertools
from time import time
from bot.logger import LOGGER
from config import Config

from ..settings import bot_set 

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Napster Manager: Gagal mengimpor 'database'.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

try:
    from .api import NapsterAPI, NapsterError
except ImportError:
    LOGGER.critical("Napster: Gagal mengimpor 'NapsterAPI' dari '.api'.")
    class NapsterAPI:
        def __init__(self, *args, **kwargs): pass
        def login(self, *args, **kwargs): 
            raise NotImplementedError("File 'NapsterAPI' inti tidak ditemukan.")
    class NapsterError(Exception): pass

class NapsterLoginManager:
    """
    Mengelola kumpulan instans klien NapsterAPI yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        if not Config.NAPSTER_API_KEY or not Config.NAPSTER_CUSTOMER_SECRET:
            LOGGER.error("Napster Manager: API_KEY atau CUSTOMER_SECRET tidak diatur di Config!")
        self.api_key = Config.NAPSTER_API_KEY
        self.customer_secret = Config.NAPSTER_CUSTOMER_SECRET
        
        self.quality = "MP3_320" # Default kualitas (320k)
        self.user_data = {} # Cache lokal (disinkronkan dari bot_set oleh user_settings.py)

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Napster dari Config
        dan memuat pengaturan kualitas default.
        """
        
        try:
            all_settings = await database.get_variable() 
            if not all_settings: all_settings = {}
            db_quality = all_settings.get('NAPSTER_QUALITY') 
            if db_quality in ["FLAC", "MP3_320", "MP3_192", "MP3_128", "MP3_64"]:
                self.quality = db_quality
                LOGGER.info(f"Napster Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Napster Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")

            LOGGER.info(f"Napster Manager: Pengaturan kualitas pengguna akan dibaca dari bot_set.")

        except Exception as e:
            LOGGER.error(f"Napster Manager: Gagal memuat kualitas default dari DB: {e}. Menggunakan default: {self.quality}")

        if not self.account_configs:
            LOGGER.warning("Napster Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"Napster Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Napster Manager: Gagal login ke SEMUA akun Napster.")
            return

        LOGGER.info(f"Napster Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun (menggunakan asyncio.to_thread)."""
        
        client = NapsterAPI(
            exception=NapsterError,
            api_key=self.api_key, 
            customer_secret=self.customer_secret
        )
        
        try:
            # Panggil login sinkron di thread terpisah
            await asyncio.to_thread(
                client.login,
                email=account['email'], 
                password=account['password'],
                current_timestamp=int(time())
            )
            LOGGER.info(f"Napster Manager: Berhasil login ke Akun #{account['id']} (User: {client.user_id})")
            return client
        except Exception as e:
            LOGGER.error(f"Napster Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> NapsterAPI | None:
        if not self._client_cycler:
            LOGGER.error("Napster Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Napster Manager: Kumpulan klien kosong.")
            return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Hanya menyimpan ke cache RAM lokal. user_settings.py menangani DB."""
        if qual in ["FLAC", "MP3_320", "MP3_192", "MP3_128", "MP3_64"]:
            self.user_data.setdefault(user_id, {})['napster_qual'] = qual
            LOGGER.debug(f"Napster Manager: Memperbarui cache RAM lokal untuk user {user_id} ke {qual}")
            
    def get_user_quality(self, user_id: int) -> str:
        """Membaca dari cache RAM lokal."""
        user_qual = self.user_data.get(user_id, {}).get('napster_qual') 
        if user_qual in ["FLAC", "MP3_320", "MP3_192", "MP3_128", "MP3_64"]:
            return user_qual
        return self.quality 

napster_manager = NapsterLoginManager(Config.NAPSTER_ACCOUNTS)
