# [GANTI SELURUH FILE: bot/helpers/highresaudio/manager.py]

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
        # [BARU] Dictionary untuk menyimpan sesi akun milik pengguna
        # Format: {user_id: HighResAudioApi_Object}
        self.user_clients = {}
        self._client_cycler = None
        
    async def initialize_clients(self):
        if not self.account_configs:
            LOGGER.warning("HighResAudio Manager: Tidak ada akun global (Bot) yang dikonfigurasi.")
            # Jangan return dulu, karena mungkin nanti ada user yang login akun sendiri
        else:
            LOGGER.info(f"HighResAudio Manager: Menginisialisasi {len(self.account_configs)} akun global...")
            tasks = []
            for account in self.account_configs:
                tasks.append(self._login_task(account))
            
            results = await asyncio.gather(*tasks)
            self.clients = [client for client in results if client is not None]
            
            if self.clients:
                LOGGER.info(f"HighResAudio Manager: Berhasil login ke {len(self.clients)} akun global.")
                self._client_cycler = itertools.cycle(self.clients)
            else:
                LOGGER.error("HighResAudio Manager: Gagal login ke SEMUA akun global.")

    async def _login_task(self, account: dict):
        proxy = account.get('proxy')
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=proxy 
        )
        
        try:
            # Menggunakan to_thread karena requests bersifat blocking
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            return client
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Gagal login ke Akun {account['email']}. Error: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return None

    # [BARU] Fungsi untuk pengguna menambahkan akun mereka sendiri
    async def add_user_account(self, user_id: int, email, password):
        LOGGER.info(f"HighResAudio: User {user_id} mencoba login akun {email}...")
        
        # Buat client baru khusus untuk user ini
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=None # User biasa biasanya direct connection (atau bisa tambah logika proxy user nanti)
        )
        
        try:
            await asyncio.to_thread(
                client.auth,
                username=email,
                password=password
            )
            
            # Jika user sebelumnya sudah punya akun, tutup sesi lama
            if user_id in self.user_clients:
                try:
                    self.user_clients[user_id].close_session()
                except: pass
            
            # Simpan sesi baru
            self.user_clients[user_id] = client
            LOGGER.info(f"HighResAudio: User {user_id} berhasil login.")
            return True, "Login Berhasil!"
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: User {user_id} gagal login: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return False, str(e)

    # [MODIFIKASI] Ambil client berdasarkan User ID
    def get_client(self, user_id: int = None) -> HighResAudioApi | None:
        # 1. Cek apakah user punya akun pribadi
        if user_id and user_id in self.user_clients:
            return self.user_clients[user_id]
        
        # 2. Jika tidak, gunakan akun global (Load Balanced)
        if self._client_cycler:
            try:
                return next(self._client_cycler)
            except StopIteration:
                pass
                
        LOGGER.error("HighResAudio Manager: Tidak ada klien yang tersedia (User maupun Global).")
        return None

    async def shutdown(self):
        LOGGER.info("HighResAudio Manager: Memulai shutdown...")
        
        # Tutup akun global
        for client in self.clients:
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
                
        # Tutup akun user
        for uid, client in self.user_clients.items():
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
        
        self.clients = []
        self.user_clients = {}
        self._client_cycler = None
        LOGGER.info("HighResAudio Manager: Semua sesi ditutup.")

highresaudio_manager = HighResAudioLoginManager(Config.HIGHRESAUDIO_ACCOUNTS)
