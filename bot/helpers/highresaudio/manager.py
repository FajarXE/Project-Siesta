# [BUAT FILE BARU: bot/helpers/highresaudio/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from .api import HighResAudioApi
except ImportError:
    class HighResAudioApi: pass 
    LOGGER.critical("HighResAudio: Gagal mengimpor 'HighResAudioApi' dari '.api'.")

class HighResAudioError(Exception):
    """Pengecualian kustom untuk HighResAudio"""
    pass

class HighResAudioLoginManager:
    """
    Mengelola kumpulan instans klien HighResAudioApi yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        # Layanan ini tidak memiliki pengaturan kualitas yang bisa dipilih
        # Ia selalu mengunduh FLAC yang tersedia.

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun HighResAudio dari Config.
        """
        if not self.account_configs:
            LOGGER.warning("HighResAudio Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"HighResAudio Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("HighResAudio Manager: Gagal login ke SEMUA akun HighResAudio.")
            return

        LOGGER.info(f"HighResAudio Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun (menggunakan asyncio.to_thread)."""
        
        client = HighResAudioApi(
            exception=HighResAudioError
        )
        
        try:
            # Panggil login sinkron di thread terpisah
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            return client
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            return None

    def get_client(self) -> HighResAudioApi | None:
        """Mengambil klien berikutnya dari rotasi (round-robin)."""
        if not self._client_cycler:
            LOGGER.error("HighResAudio Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("HighResAudio Manager: Kumpulan klien kosong.")
            return None

# Inisialisasi manajer global
highresaudio_manager = HighResAudioLoginManager(Config.HIGHRESAUDIO_ACCOUNTS)
