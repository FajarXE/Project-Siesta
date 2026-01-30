# [GANTI FILE: bot/helpers/highresaudio/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from .api import HighResAudioApi
except ImportError:
    class HighResAudioApi: 
        def close_session(self): pass
    LOGGER.critical("HighResAudio: Gagal mengimpor 'HighResAudioApi' dari '.api'.")

class HighResAudioError(Exception):
    pass

class HighResAudioLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
    async def initialize_clients(self):
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
        # --- PERBAIKAN: Ambil proxy dari config akun ---
        proxy = account.get('proxy')
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=proxy # Teruskan proxy ke API
        )
        # -----------------------------------------------
        
        try:
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            return client
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            if hasattr(client, 'close_session'):
                await asyncio.to_thread(client.close_session)
            return None

    def get_client(self) -> HighResAudioApi | None:
        if not self._client_cycler:
            LOGGER.error("HighResAudio Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("HighResAudio Manager: Kumpulan klien kosong.")
            return None

    async def shutdown(self):
        LOGGER.info(f"HighResAudio Manager: Memulai shutdown... Menutup {len(self.clients)} sesi.")
        tasks = []
        for client in self.clients:
            if hasattr(client, 'close_session'):
                tasks.append(asyncio.to_thread(client.close_session))
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Terjadi error saat shutdown: {e}")
            
        self.clients = []
        self._client_cycler = None
        LOGGER.info("HighResAudio Manager: Semua sesi klien ditutup.")

highresaudio_manager = HighResAudioLoginManager(Config.HIGHRESAUDIO_ACCOUNTS)
