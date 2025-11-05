# [GANTI FILE: bot/helpers/deezer/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from .dzapi import DeezerAPI

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Deezer Manager: Gagal mengimpor 'database'. Fungsi pemuatan kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
    database = DummyDatabase()


class DeezerLoginManager:
    """
    Mengelola kumpulan instans klien DeezerAPI yang sudah login.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        self.quality = "FLAC" 
        self.user_data = {} 

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Deezer dari Config
        dan memuat pengaturan kualitas default.
        """
        
        # --- PERBAIKAN: Muat Kualitas Default ---
        try:
            all_settings = await database.get_variable() # Ambil SEMUA pengaturan
            if not all_settings:
                all_settings = {}
                
            db_quality = all_settings.get('DEEZER_QUALITY')
            
            if db_quality in ["FLAC", "MP3_320", "MP3_128"]:
                self.quality = db_quality
                LOGGER.info(f"Deezer Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Deezer Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")
        except Exception as e:
            LOGGER.error(f"Deezer Manager: Gagal memuat kualitas dari DB: {e}. Menggunakan default: {self.quality}")
        # --- PERBAIKAN SELESAI ---

        if not self.account_configs:
            LOGGER.warning("Deezer Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"Deezer Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Deezer Manager: Gagal login ke SEMUA akun Deezer. Unduhan Deezer tidak akan berfungsi.")
            return

        LOGGER.info(f"Deezer Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun."""
        client = DeezerAPI()
        try:
            await client.login(arl=account['arl'])
            LOGGER.info(f"Deezer Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"Deezer Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> DeezerAPI | None:
        """
        Mendapatkan klien berikutnya dari kumpulan (round-robin).
        """
        if not self._client_cycler:
            LOGGER.error("Deezer Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Deezer Manager: Kumpulan klien kosong.")
            return None

    async def setup_quality(self, user_id: int, qual: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["FLAC", "MP3_320", "MP3_128"]:
            self.user_data[user_id]['deezer_qual'] = qual
            LOGGER.debug(f"Deezer Manager: Mengatur kualitas user {user_id} ke {qual}")

    def get_user_quality(self, user_id: int) -> str:
        """Mendapatkan kualitas untuk pengguna, fallback ke default."""
        user_qual = self.user_data.get(user_id, {}).get('deezer_qual')
        if user_qual in ["FLAC", "MP3_320", "MP3_128"]:
            return user_qual
        return self.quality 

deezer_manager = DeezerLoginManager(Config.DEEZER_ACCOUNTS)
