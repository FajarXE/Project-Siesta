# [FILE BARU: bot/helpers/deezer/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from .dzapi import DeezerAPI

class DeezerLoginManager:
    """
    Mengelola kumpulan instans klien DeezerAPI yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] # Daftar instans DeezerAPI yang berhasil login
        self._client_cycler = None

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Deezer dari Config
        dan menyimpannya di self.clients.
        """
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

# --- Buat satu instans global dari manajer ---
# Manajer ini akan diimpor oleh bot utama Anda.
deezer_manager = DeezerLoginManager(Config.DEEZER_ACCOUNTS)
