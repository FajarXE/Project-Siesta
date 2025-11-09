# [BUAT FILE BARU: bot/helpers/idagio/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

from ..settings import bot_set 

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Idagio Manager: Gagal mengimpor 'database'.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

try:
    from .api import IdagioApi, IdagioError
except ImportError:
    LOGGER.critical("Idagio: Gagal mengimpor 'IdagioApi' dari '.api'.")
    class IdagioApi:
        def __init__(self, *args, **kwargs): pass
        def login(self, *args, **kwargs): 
            raise NotImplementedError("File 'IdagioApi' inti tidak ditemukan.")
    class IdagioError(Exception): pass

class IdagioLoginManager:
    """
    Mengelola kumpulan instans klien IdagioApi yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        # Kualitas default: 90 (FLAC)
        self.quality = "FLAC" 
        self.user_data = {} # Cache lokal (disinkronkan dari bot_set oleh user_settings.py)

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Idagio dari Config
        dan memuat pengaturan kualitas default.
        """
        
        try:
            all_settings = await database.get_variable() 
            if not all_settings: all_settings = {}
            db_quality = all_settings.get('IDAGIO_QUALITY') 
            if db_quality in ["FLAC", "MP3_320", "MP3_160"]:
                self.quality = db_quality
                LOGGER.info(f"Idagio Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Idagio Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")

            LOGGER.info(f"Idagio Manager: Pengaturan kualitas pengguna akan dibaca dari bot_set.")

        except Exception as e:
            LOGGER.error(f"Idagio Manager: Gagal memuat kualitas default dari DB: {e}. Menggunakan default: {self.quality}")

        if not self.account_configs:
            LOGGER.warning("Idagio Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"Idagio Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Idagio Manager: Gagal login ke SEMUA akun Idagio.")
            return

        LOGGER.info(f"Idagio Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun (menggunakan asyncio.to_thread)."""
        
        client = IdagioApi(
            exception=IdagioError
        )
        
        try:
            # Panggil login sinkron di thread terpisah
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            # client.valid_account() sudah dipanggil di dalam auth()
            LOGGER.info(f"Idagio Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"Idagio Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> IdagioApi | None:
        if not self._client_cycler:
            LOGGER.error("Idagio Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Idagio Manager: Kumpulan klien kosong.")
            return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Hanya menyimpan ke cache RAM lokal. user_settings.py menangani DB."""
        if qual in ["FLAC", "MP3_320", "MP3_160"]:
            self.user_data.setdefault(user_id, {})['idagio_qual'] = qual
            LOGGER.debug(f"Idagio Manager: Memperbarui cache RAM lokal untuk user {user_id} ke {qual}")
            
    def get_user_quality(self, user_id: int) -> str:
        """Membaca dari cache RAM lokal."""
        user_qual = self.user_data.get(user_id, {}).get('idagio_qual') 
        if user_qual in ["FLAC", "MP3_320", "MP3_160"]:
            return user_qual
        return self.quality 

idagio_manager = IdagioLoginManager(Config.IDAGIO_ACCOUNTS)
