# [FILE BARU: bot/helpers/soundcloud/manager.py]

import asyncio
from bot.logger import LOGGER
from config import Config

try:
    from .api import SoundcloudAPI
except ImportError:
    LOGGER.critical("Soundcloud: Gagal mengimpor 'SoundcloudAPI' dari 'bot/helpers/soundcloud/api.py'.")
    class SoundcloudAPI:
        def __init__(self, *args, **kwargs): pass

class SoundcloudLoginManager:
    """
    Mengelola instance klien SoundcloudAPI.
    Tidak seperti Beatport, Soundcloud tidak memerlukan pool login,
    hanya satu 'access_token' (client_id) yang valid.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self):
        self.token = Config.SOUNDCLOUD_ACCESS_TOKEN
        self.api_client: SoundcloudAPI | None = None
        
        # Kualitas: 'original' (mencoba file asli) atau 'stream' (hanya HLS/progresif)
        self.quality = "original" 
        self.user_data = {} 

    async def initialize_clients(self):
        """
        Menginisialisasi klien API tunggal.
        """
        if not self.token:
            LOGGER.warning("Soundcloud Manager: 'SOUNDCLOUD_ACCESS_TOKEN' tidak diatur di config. Modul tidak akan aktif.")
            return

        try:
            # Di masa depan, di sini Anda bisa menambahkan logika
            # untuk 'scrape' client_id baru jika yang lama kedaluwarsa.
            # Untuk saat ini, kita gunakan token dari Config.
            self.api_client = SoundcloudAPI(self.token)
            LOGGER.info("Soundcloud Manager: Berhasil diinisialisasi dengan access token.")
        except Exception as e:
            LOGGER.error(f"Soundcloud Manager: Gagal menginisialisasi: {e}")
            self.api_client = None

    def get_client(self) -> SoundcloudAPI | None:
        """
        Mendapatkan klien API yang sudah diinisialisasi.
        """
        if not self.api_client:
            LOGGER.error("Soundcloud Manager: Klien API tidak tersedia (belum diinisialisasi atau gagal).")
            return None
        return self.api_client
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["original", "stream"]:
            self.user_data[user_id]['soundcloud_qual'] = qual
            LOGGER.debug(f"Soundcloud Manager: Mengatur kualitas user {user_id} ke {qual}")

    def get_user_quality(self, user_id: int) -> str:
        """Mendapatkan kualitas untuk pengguna, fallback ke default."""
        user_qual = self.user_data.get(user_id, {}).get('soundcloud_qual')
        if user_qual in ["original", "stream"]:
            return user_qual
        return self.quality 

# Buat instance manager tunggal
soundcloud_manager = SoundcloudLoginManager()
