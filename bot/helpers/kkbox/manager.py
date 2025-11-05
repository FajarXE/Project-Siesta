# [GANTI FILE: bot/helpers/kkbox/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    # --- BLOK FALLBACK YANG DIISI ---
    LOGGER.critical("KKBox Manager: Gagal mengimpor 'database'. Fungsi pemuatan kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
    database = DummyDatabase()
    # --- BATAS BLOK ---

try:
    from .api import KkboxAPI
except ImportError:
    # --- BLOK FALLBACK YANG DIISI ---
    LOGGER.critical("KKBox: Gagal mengimpor 'KkboxAPI' dari 'bot/helpers/kkbox/api.py'. File inti tidak ada.")
    class KkboxAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("File 'KkboxAPI' inti tidak ditemukan.")
        async def close_session(self): pass
    # --- BATAS BLOK ---

# Pengecualian kustom sederhana untuk diteruskan
class KKBoxError(Exception):
    pass

class KKBoxLoginManager:
    """
    Mengelola kumpulan instans klien KkboxAPI yang sudah login.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        # Muat Kunci Global dari Config
        if not Config.KKBOX_KC1_KEY or not Config.KKBOX_SECRET_KEY:
            LOGGER.error("KKBox Manager: Kunci KC1 atau Secret tidak diatur di Config!")
            self.kc1_key = ""
            self.secret_key = ""
        else:
            self.kc1_key = Config.KKBOX_KC1_KEY
            self.secret_key = Config.KKBOX_SECRET_KEY
        
        # Sesuaikan ini dengan kualitas KKBox (dari interface.py)
        self.quality = "hifi" # Default 'hifi' (Lossless 16-bit), bukan 'hires'
        self.user_data = {} 

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun KKBox dari Config
        dan memuat pengaturan kualitas default.
        """
        
        # --- Muat Kualitas Default ---
        try:
            all_settings = await database.get_variable() # Ambil SEMUA pengaturan
            if not all_settings:
                all_settings = {}

            # Ganti nama variabel DB
            db_quality = all_settings.get('KKBOX_QUALITY') 
            
            # Ganti dengan kualitas KKBox
            if db_quality in ["128k", "192k", "320k", "hifi", "hires"]:
                self.quality = db_quality
                LOGGER.info(f"KKBox Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"KKBox Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")
        except Exception as e:
            LOGGER.error(f"KKBox Manager: Gagal memuat kualitas dari DB: {e}. Menggunakan default: {self.quality}")
        # --- Selesai ---

        if not self.account_configs:
            LOGGER.warning("KKBox Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"KKBox Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("KKBox Manager: Gagal login ke SEMUA akun KKBox.")
            return

        LOGGER.info(f"KKBox Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun (menggunakan asyncio.to_thread)."""
        
        # Buat instans client
        # Kita meneruskan KKBoxError sebagai 'exception' yang dibutuhkan
        client = KkboxAPI(
            exception=KKBoxError,
            kc1_key=self.kc1_key, 
            secret_key=self.secret_key
        )
        
        try:
            # Jalankan login sinkron di thread terpisah
            await asyncio.to_thread(
                client.login,
                email=account['email'], 
                password=account['password']
            )
            LOGGER.info(f"KKBox Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"KKBox Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> KkboxAPI | None:
        """
        Mendapatkan klien berikutnya dari kumpulan (round-robin).
        """
        if not self._client_cycler:
            LOGGER.error("KKBox Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("KKBox Manager: Kumpulan klien kosong.")
            return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        # Ganti dengan kualitas KKBox
        if qual in ["128k", "192k", "320k", "hifi", "hires"]:
            self.user_data[user_id]['kkbox_qual'] = qual # Ganti nama var
            LOGGER.debug(f"KKBox Manager: Mengatur kualitas user {user_id} ke {qual}")

    def get_user_quality(self, user_id: int) -> str:
        """Mendapatkan kualitas untuk pengguna, fallback ke default."""
        user_qual = self.user_data.get(user_id, {}).get('kkbox_qual') # Ganti nama var
        # Ganti dengan kualitas KKBox
        if user_qual in ["128k", "192k", "320k", "hifi", "hires"]:
            return user_qual
        return self.quality 

# Buat instans global
kkbox_manager = KKBoxLoginManager(Config.KKBOX_ACCOUNTS)
