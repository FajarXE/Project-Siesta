# [GANTI FILE: bot/helpers/tidal/manager.py]

import asyncio
import itertools
import random
from bot.logger import LOGGER
from config import Config
from .tidal_api import TidalApi 

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Tidal Manager: Gagal mengimpor 'database'. Fungsi login/kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()


class TidalLoginManager:
    """
    Mengelola kumpulan instans klien TidalApi yang sudah login.
    """
    def __init__(self):
        self.clients = [] 
        self._client_cycler = None
        
        # --- MODIFIKASI: Tambahkan default MQA & Convert ---
        self.quality = "LOSSLESS" 
        self.spatial = "OFF"
        # Ambil default global dari Config (sekarang "ON" atau "OFF")
        self.mqa_fix = Config.TIDAL_FIX_MQA
        self.convert_m4a = Config.TIDAL_CONVERT_M4A
        # --- AKHIR MODIFIKASI ---
        
        self.user_data = {}       

    async def initialize_clients(self):
        """
        Memuat semua akun Tidal dari database dan menginisialisasinya.
        """
        self.clients = [] 
        LOGGER.info("Tidal Manager: Menginisialisasi klien...")
        
        try:
            all_settings = await database.get_variable() # Ambil SEMUA pengaturan
            if not all_settings:
                all_settings = {}
                
            # 1. Muat Pengaturan Kualitas Default
            db_quality = all_settings.get('TIDAL_QUALITY')
            if db_quality in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
                self.quality = db_quality
                LOGGER.info(f"Tidal Manager: Kualitas default dimuat dari DB: {self.quality}")
            
            db_spatial = all_settings.get('TIDAL_SPATIAL')
            if db_spatial:
                self.spatial = db_spatial
                LOGGER.info(f"Tidal Manager: Kualitas spasial default dimuat dari DB: {self.spatial}")
            
            # 2. Muat pengaturan MQA global (Admin)
            db_mqa_fix = all_settings.get('TIDAL_MQA_FIX')
            if db_mqa_fix in ["ON", "OFF"]:
                self.mqa_fix = db_mqa_fix
                LOGGER.info(f"Tidal Manager: Perbaikan MQA default dimuat dari DB: {self.mqa_fix}")
            
            # 3. Muat pengaturan Convert M4A global (Admin)
            db_convert_m4a = all_settings.get('TIDAL_CONVERT_M4A')
            if db_convert_m4a in ["ON", "OFF"]:
                self.convert_m4a = db_convert_m4a
                LOGGER.info(f"Tidal Manager: Konversi M4A default dimuat dari DB: {self.convert_m4a}")
            
            # 4. Muat Daftar Akun dari DB
            accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
            
        except Exception as e:
            LOGGER.error(f"Tidal Manager: Gagal memuat data dari DB: {e}. Menggunakan default.")
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
            clients_list = list(self.clients)
            random.shuffle(clients_list)
            self._client_cycler = itertools.cycle(clients_list)
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Tidal Manager: Kumpulan klien kosong.")
            return None

    # --- Fungsi Helper Kualitas ---
    
    # --- MODIFIKASI: Tambahkan parameter convert_m4a ---
    async def setup_user_settings(self, user_id: int, qual: str = None, spatial: str = None, mqa_fix: str = None, convert_m4a: str = None):
        """Mengatur cache kualitas, mqa, & convert untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
            
        if qual in ["LOW", "HIGH", "LOSSLESS", "HI_RES"]:
            self.user_data[user_id]['tidal_qual'] = qual
            LOGGER.debug(f"Tidal Manager: Mengatur kualitas user {user_id} ke {qual}")
            
        if spatial in ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']:
            self.user_data[user_id]['tidal_spatial'] = spatial
            LOGGER.debug(f"Tidal Manager: Mengatur spasial user {user_id} ke {spatial}")
            
        if mqa_fix in ['ON', 'OFF']:
            self.user_data[user_id]['tidal_mqa_fix'] = mqa_fix
            LOGGER.debug(f"Tidal Manager: Mengatur MQA Fix user {user_id} ke {mqa_fix}")
            
        if convert_m4a in ['ON', 'OFF']:
            self.user_data[user_id]['tidal_convert_m4a'] = convert_m4a
            LOGGER.debug(f"Tidal Manager: Mengatur Convert M4A user {user_id} ke {convert_m4a}")
    # --- AKHIR MODIFIKASI ---

    # --- MODIFIKASI: Kembalikan 4 nilai ---
    def get_user_quality_settings(self, user_id: int) -> tuple[str, str, str, str]:
        """Mendapatkan kualitas, spasial, mqa, & convert untuk pengguna, fallback ke default."""
        user_dict = self.user_data.get(user_id, {})
        user_qual = user_dict.get('tidal_qual', self.quality)
        user_spatial = user_dict.get('tidal_spatial', self.spatial)
        user_mqa_fix = user_dict.get('tidal_mqa_fix', self.mqa_fix)
        user_convert_m4a = user_dict.get('tidal_convert_m4a', self.convert_m4a) # <-- Tambahkan ini
        return user_qual, user_spatial, user_mqa_fix, user_convert_m4a # <-- Kembalikan 4 nilai
    # --- AKHIR MODIFIKASI ---
    
    # --- TAMBAHAN BARU: Helper untuk tombol ---
    async def get_user_qualities_dict(self, user_id: int) -> dict:
        """Mendapatkan dict kualitas dengan tanda centang untuk tombol."""
        user_qual, _, __, ___ = self.get_user_quality_settings(user_id) # Diperbarui untuk 4 nilai
        qualities = {
            "LOW": "LOW",
            "HIGH": "HIGH",
            "LOSSLESS": "LOSSLESS",
            "HI_RES": "HI_RES"
        }
        qualities[user_qual] += " ✅"
        return qualities

    async def get_user_spatial_dict(self, user_id: int) -> str:
        """Mendapatkan pengaturan spasial pengguna saat ini."""
        _, user_spatial, __, ___ = self.get_user_quality_settings(user_id) # Diperbarui untuk 4 nilai
        return user_spatial
    # --- BATAS TAMBAHAN ---


tidal_manager = TidalLoginManager()
