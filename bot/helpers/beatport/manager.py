# [FILE BARU: bot/helpers/beatport/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

# PENTING: Impor ini mengasumsikan Anda akan membuat 
# file 'api.py' dengan kelas 'BeatportAPI'
try:
    from .api import BeatportAPI
except ImportError:
    LOGGER.critical("Beatport: Gagal mengimpor 'BeatportAPI' dari 'bot/helpers/beatport/api.py'. File inti tidak ada.")
    # Buat kelas dummy agar bot tidak crash saat startup
    class BeatportAPI:
        def __init__(self, *args, **kwargs):
            pass
        async def login(self, *args, **kwargs):
            raise NotImplementedError("File 'BeatportAPI' inti tidak ditemukan.")
        async def close_session(self):
            pass


class BeatportLoginManager:
    """
    Mengelola kumpulan instans klien BeatportAPI yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] # Daftar instans BeatportAPI yang berhasil login
        self._client_cycler = None

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Beatport dari Config
        """
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
            # Asumsi login menggunakan email dan password
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

# Buat satu instans global dari manajer
beatport_manager = BeatportLoginManager(Config.BEATPORT_ACCOUNTS)
