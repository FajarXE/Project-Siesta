# [FILE BARU: bot/helpers/tidal/manager.py]

import asyncio
import itertools
import random
from bot.logger import LOGGER
from config import Config
from .tidal_api import TidalApi # Impor kelas TidalApi, bukan instans

# Impor database
try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Tidal Manager: Gagal mengimpor 'database'. Fungsi login/kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return None
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()


class TidalLoginManager:
    """
    Mengelola kumpulan instans klien TidalApi yang sudah login.
    """
    def __init__(self):
        self.clients = [] # Daftar instans TidalApi yang berhasil login
        self._client_cycler = None
        
        # Pengaturan Kualitas
        self.quality = "LOSSLESS" # Default sebelum dimuat dari DB
        self.spatial = "OFF"      # Default sebelum dimuat dari DB
        self.user_data = {}       # Cache untuk pengaturan per-pengguna

    async def initialize_clients(self):
        """
        Memuat semua akun Tidal dari database dan menginisialisasinya.
        """
        self.clients = [] # Hapus klien lama jika ada
        LOGGER.info("Tidal Manager: Menginisialisasi klien...")

        # 1. Muat Pengaturan Kualitas Default
        try:
            db_quality = (await database.get_variable({"key": 'TIDAL_QUALITY'})).get("value")
            if db_quality in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
                self.quality = db_quality
                LOGGER.info(f"Tidal Manager: Kualitas default dimuat dari DB: {self.quality}")
            
            db_spatial = (await database.get_variable({"key": 'TIDAL_SPATIAL'})).get("value")
            if db_spatial:
                self.spatial = db_spatial
                LOGGER.info(f"Tidal Manager: Kualitas spasial default dimuat dari DB: {self.spatial}")
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal memuat kualitas dari DB: {e}. Menggunakan default.")

        # 2. Muat Daftar Akun dari DB
        try:
            accounts_list_doc = await database.get_variable({"key": "TIDAL_ACCOUNTS_LIST"})
            accounts_list = accounts_list_doc.get("value", []) if accounts_list_doc else []
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal memuat daftar akun dari DB: {e}")
            accounts_list = []

        if not accounts_list:
            LOGGER.warning("Tidal Manager: Tidak ada akun di database untuk diinisialisasi.")
            return

        LOGGER.info(f"Tidal Manager: Menginisialisasi {len(accounts_list)} akun Tidal...")
        tasks = []
        for i, auth_data in enumerate(accounts_list):
            tasks.append(self._login_task(auth_data, i + 1))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Tidal Manager: Gagal login ke SEMUA akun Tidal.")
            return

        LOGGER.info(f"Tidal Manager: Berhasil login ke {len(self.clients)} dari {len(accounts_list)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, auth_data: dict, account_id: int):
        """Tugas login untuk satu akun."""
        client = TidalApi()
        try:
            # login_from_saved akan me-refresh token
            await client.login_from_saved(auth_data)
            LOGGER.info(f"Tidal Manager: Berhasil login ke Akun #{account_id} (User {client.user_id})")
            return client
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal login/refresh Akun #{account_id} (User {auth_data.get('user_id')}). Error: {e}")
            return None

    def get_client(self) -> TidalApi | None:
        """
        Mendapatkan klien berikutnya dari kumpulan (round-robin).
        """
        if not self._client_cycler:
            LOGGER.error("Tidal Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            # Acak daftar klien sebelum mengambil berikutnya untuk distribusi yang lebih baik
            # jika salah satu klien region-locked
            clients_list = list(self.clients)
            random.shuffle(clients_list)
            self._client_cycler = itertools.cycle(clients_list)
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Tidal Manager: Kumpulan klien kosong.")
            return None

    # --- Fungsi Helper Kualitas ---
    
    async def setup_quality(self, user_id: int, qual: str = None, spatial: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
            self.user_data[user_id]['tidal_qual'] = qual
            LOGGER.debug(f"Tidal Manager: Mengatur kualitas user {user_id} ke {qual}")
        if spatial in ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']:
            self.user_data[user_id]['tidal_spatial'] = spatial
            LOGGER.debug(f"Tidal Manager: Mengatur spasial user {user_id} ke {spatial}")

    def get_user_quality_settings(self, user_id: int) -> tuple[str, str]:
        """Mendapatkan kualitas & spasial untuk pengguna, fallback ke default."""
        user_dict = self.user_data.get(user_id, {})
        user_qual = user_dict.get('tidal_qual', self.quality)
        user_spatial = user_dict.get('tidal_spatial', self.spatial)
        return user_qual, user_spatial

# Buat satu instans global dari manajer
tidal_manager = TidalLoginManager()
