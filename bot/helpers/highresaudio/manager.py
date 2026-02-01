# [GANTI SELURUH FILE: bot/helpers/highresaudio/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config
from bot.helpers.database.mongo_async import database # Import Database

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
        # Dictionary untuk menyimpan sesi akun milik pengguna
        self.user_clients = {}
        self._client_cycler = None
        
    async def initialize_clients(self):
        # 1. INISIALISASI AKUN GLOBAL (BOT)
        if self.account_configs:
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
        else:
            LOGGER.warning("HighResAudio Manager: Tidak ada akun global (Bot) yang dikonfigurasi.")

        # 2. [BARU] MUAT AKUN PENGGUNA DARI DATABASE
        LOGGER.info("HighResAudio Manager: Memuat sesi pengguna dari database...")
        # Ambil semua data user yang punya 'highresaudio_auth'
        # Asumsi: Anda menyimpan kredensial di field 'highresaudio_auth' dalam format 'email:password'
        # Atau kita iterasi semua user untuk cek
        all_users = await database.get_all_users() # Pastikan fungsi ini ada di helper database Anda
        
        count_relogin = 0
        for user_doc in all_users:
            user_id = user_doc.get('user_id')
            # Cek apakah user ini punya data login HRA yang tersimpan
            hra_data = user_doc.get('highresaudio_auth') # Format: "email:password"
            
            if hra_data and ":" in hra_data:
                try:
                    email, password = hra_data.split(":", 1)
                    # Login diam-diam (Silent Login)
                    success, _ = await self.add_user_account(user_id, email, password, save_db=False)
                    if success:
                        count_relogin += 1
                except Exception as e:
                    LOGGER.warning(f"Gagal restore sesi HRA untuk user {user_id}: {e}")

        if count_relogin > 0:
            LOGGER.info(f"HighResAudio Manager: Berhasil memulihkan {count_relogin} sesi pengguna.")

    async def _login_task(self, account: dict):
        proxy = account.get('proxy')
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=proxy 
        )
        try:
            await asyncio.to_thread(
                client.auth,
                username=account['email'], 
                password=account['password']
            )
            return client
        except Exception as e:
            LOGGER.error(f"HighResAudio Manager: Gagal login ke Akun Global {account['email']}. Error: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return None

    # [MODIFIKASI] Tambahkan parameter save_db
    async def add_user_account(self, user_id: int, email, password, save_db=True):
        LOGGER.info(f"HighResAudio: User {user_id} mencoba login akun {email}...")
        
        client = HighResAudioApi(
            exception=HighResAudioError,
            proxy=None 
        )
        
        try:
            await asyncio.to_thread(
                client.auth,
                username=email,
                password=password
            )
            
            if user_id in self.user_clients:
                try: self.user_clients[user_id].close_session()
                except: pass
            
            self.user_clients[user_id] = client
            
            # [BARU] Simpan ke Database agar awet
            if save_db:
                auth_str = f"{email}:{password}"
                await database.save_user_settings(user_id, {'highresaudio_auth': auth_str})
            
            LOGGER.info(f"HighResAudio: User {user_id} berhasil login.")
            return True, "Login Berhasil!"
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: User {user_id} gagal login: {e}")
            if hasattr(client, 'close_session'):
                client.close_session()
            return False, str(e)

    async def remove_user_account(self, user_id: int):
        # 1. Hapus Sesi Memory
        if user_id in self.user_clients:
            try: self.user_clients[user_id].close_session()
            except: pass
            del self.user_clients[user_id]
            
        # 2. Hapus dari Database
        await database.save_user_settings(user_id, {'highresaudio_auth': None})

    def get_client(self, user_id: int = None) -> HighResAudioApi | None:
        if user_id and user_id in self.user_clients:
            return self.user_clients[user_id]
        
        if self._client_cycler:
            try:
                return next(self._client_cycler)
            except StopIteration:
                pass
                
        # Fallback jika tidak ada client sama sekali
        return None

    async def shutdown(self):
        LOGGER.info("HighResAudio Manager: Memulai shutdown...")
        for client in self.clients:
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
        for uid, client in self.user_clients.items():
            if hasattr(client, 'close_session'):
                try: client.close_session()
                except: pass
        
        self.clients = []
        self.user_clients = {}
        self._client_cycler = None

highresaudio_manager = HighResAudioLoginManager(Config.HIGHRESAUDIO_ACCOUNTS)
