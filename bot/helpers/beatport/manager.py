# [GANTI FILE: bot/helpers/beatport/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Beatport Manager: Gagal mengimpor 'database'. Fungsi pemuatan kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
    database = DummyDatabase()

try:
    from .api import BeatportAPI
except ImportError:
    LOGGER.critical("Beatport: Gagal mengimpor 'BeatportAPI' dari 'bot/helpers/beatport/api.py'. File inti tidak ada.")
    class BeatportAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("File 'BeatportAPI' inti tidak ditemukan.")
        async def close_session(self): pass


class BeatportLoginManager:
    """
    Mengelola kumpulan instans klien BeatportAPI yang sudah login.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        self.quality = "lossless" 
        self.user_data = {} 

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Beatport dari Config
        dan memuat pengaturan kualitas default.
        """
        
        # --- PERBAIKAN: Muat Kualitas Default ---
        try:
            all_settings = await database.get_variable() # Ambil SEMUA pengaturan
            if not all_settings:
                all_settings = {}

            db_quality = all_settings.get('BEATPORT_QUALITY')
            
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
                LOGGER.info(f"Beatport Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Beatport Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")
        except Exception as e:
            LOGGER.error(f"Beatport Manager: Gagal memuat kualitas dari DB: {e}. Menggunakan default: {self.quality}")
        # --- PERBAIKAN SELESAI ---

        if not self.account_configs:
            LOGGER.warning("Beatport Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"Beatport Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Beatport Manager: Gagal login ke SEMUA akun Beatport.")
            return

        LOGGER.info(f"Beatport Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun."""
        client = BeatportAPI()
        try:
            await client.login(
                email=account['email'], 
                password=account['password']
            )
            LOGGER.info(f"Beatport Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"Beatport Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> BeatportAPI | None:
        """
        Mendapatkan klien berikutnya dari kumpulan (round-robin).
        """
        if not self._client_cycler:
            LOGGER.error("Beatport Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Beatport Manager: Kumpulan klien kosong.")
            return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatport_qual'] = qual
            LOGGER.debug(f"Beatport Manager: Mengatur kualitas user {user_id} ke {qual}")

    def get_user_quality(self, user_id: int) -> str:
        """Mendapatkan kualitas untuk pengguna, fallback ke default."""
        user_qual = self.user_data.get(user_id, {}).get('beatport_qual')
        if user_qual in ["lossless", "high", "medium"]:
            return user_qual
        return self.quality 

    # --- TAMBAHAN BARU: Metode Shutdown ---
    async def shutdown(self):
        """Menutup semua sesi klien BeatportAPI yang dikelola."""
        LOGGER.info(f"Beatport Manager: Memulai shutdown... Menutup {len(self.clients)} sesi klien.")
        tasks = []
        for client in self.clients:
            # Memanggil 'close_session' sesuai dengan nama metode di api.py
            if hasattr(client, 'close_session'):
                tasks.append(client.close_session())
        
        # Jalankan semua tugas penutupan secara bersamaan
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            LOGGER.error(f"Beatport Manager: Terjadi error saat shutdown: {e}")
            
        self.clients = []
        self._client_cycler = None
        LOGGER.info("Beatport Manager: Semua sesi klien telah ditutup.")
    # --- AKHIR TAMBAHAN ---

beatport_manager = BeatportLoginManager(Config.BEATPORT_ACCOUNTS)
