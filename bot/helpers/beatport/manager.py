# [GANTI FILE: bot/helpers/beatport/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Beatport Manager: Gagal mengimpor 'database'.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

try:
    from .api import BeatportAPI, BeatportError
except ImportError:
    LOGGER.critical("Beatport: Gagal mengimpor 'BeatportAPI'.")
    class BeatportAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("API Error")
        async def close_session(self): pass


class BeatportLoginManager:
    def __init__(self, env_account_configs: list):
        self.env_account_configs = env_account_configs
        
        # GLOBAL CLIENTS (Dari .env) - Untuk user yang tidak login
        self.global_clients = [] 
        self._global_cycler = None
        
        # PRIVATE CLIENTS (Dari DB) - Mapping: user_id -> BeatportAPI Instance
        self.user_clients = {} 
        
        self.quality = "lossless" 
        self.user_data = {} 

    async def initialize_clients(self):
        """Memuat akun Global (.env) dan Akun User (DB)."""
        saved_tokens = {}
        user_sessions = {}
        
        try:
            all_settings = await database.get_variable() or {}
            
            # Load Global Quality
            db_quality = all_settings.get('BEATPORT_QUALITY')
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
            
            # Load Tokens Cache
            saved_tokens = all_settings.get('BEATPORT_TOKENS', {})
            
            # Load User Sessions (Format DB: {user_id: {'email': '...', 'password': '...'}})
            user_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
            # Pastikan key user_sessions adalah integer
            user_sessions = {int(k): v for k, v in user_sessions.items()}
            
        except Exception: pass

        # 1. INIT GLOBAL CLIENTS (.env)
        self.global_clients = []
        tasks_env = []
        LOGGER.info(f"Beatport Manager: Loading {len(self.env_account_configs)} global accounts...")
        
        for account in self.env_account_configs:
            token_data = saved_tokens.get(account['email'])
            tasks_env.append(self._login_task(account, token_data))
        
        results_env = await asyncio.gather(*tasks_env)
        self.global_clients = [c for c in results_env if c]
        if self.global_clients:
            self._global_cycler = itertools.cycle(self.global_clients)

        # 2. INIT PRIVATE USER CLIENTS (DB)
        self.user_clients = {}
        tasks_user = []
        user_ids = []
        
        if user_sessions:
            LOGGER.info(f"Beatport Manager: Loading {len(user_sessions)} private user accounts...")
            for uid, account in user_sessions.items():
                token_data = saved_tokens.get(account['email'])
                # Pass user_id agar kita tahu ini punya siapa
                tasks_user.append(self._login_task(account, token_data))
                user_ids.append(uid)
            
            results_user = await asyncio.gather(*tasks_user)
            
            for uid, client in zip(user_ids, results_user):
                if client:
                    self.user_clients[uid] = client
                    client.owner_id = uid # Tandai client ini punya siapa

        LOGGER.info(f"Beatport Manager Ready. Global: {len(self.global_clients)}, Private: {len(self.user_clients)}")
        await self.save_all_tokens()

    async def _login_task(self, account: dict, saved_token: dict = None):
        client = BeatportAPI()
        email, password = account['email'], account['password']
        
        # Proxy
        proxy = account.get('proxy')
        if proxy: client.proxy = proxy

        # Coba Token
        if saved_token and saved_token.get('refresh_token'):
            try:
                saved_token['email'] = email
                await client.load_session(saved_token)
                await client.refresh()
                return client
            except Exception: pass
        
        # Coba Password
        try:
            await client.login(email=email, password=password)
            return client
        except Exception as e:
            LOGGER.error(f"Beatport Login Failed {email}: {e}")
            return None

    # --- USER MANAGEMENT ---

    async def add_user_account(self, user_id: int, email, password):
        """Login akun pribadi untuk User ID tertentu."""
        # 1. Cek Login
        temp_client = BeatportAPI()
        await temp_client.login(email, password)
        temp_client.owner_id = user_id
        
        # 2. Simpan ke Memory (Gantikan sesi lama jika ada)
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
        self.user_clients[user_id] = temp_client
        
        # 3. Simpan ke DB
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
        
        # MongoDB kadang menyimpan key dict sebagai string, kita pastikan konversi saat load/save
        user_sessions[str(user_id)] = {"email": email, "password": password}
        
        await database.set_variable('BEATPORT_USER_SESSIONS', user_sessions)
        await self.save_all_tokens() # Cache token baru
        return True

    async def remove_user_account(self, user_id: int):
        """Hapus sesi pribadi user."""
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
            del self.user_clients[user_id]
        
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATPORT_USER_SESSIONS', {})
        
        if str(user_id) in user_sessions:
            del user_sessions[str(user_id)]
            await database.set_variable('BEATPORT_USER_SESSIONS', user_sessions)
            return True
        return False

    def get_client(self, user_id: int = None) -> BeatportAPI | None:
        """
        PRIORITAS:
        1. Akun Pribadi (jika user_id punya sesi)
        2. Akun Global (Fallback)
        """
        # Cek Akun Pribadi
        if user_id and user_id in self.user_clients:
            # Cek sesi masih hidup/valid? (Opsional: implementasi cek expire sederhana)
            return self.user_clients[user_id]
            
        # Fallback ke Global
        if self._global_cycler:
            try: return next(self._global_cycler)
            except: pass
            
        return None
    
    def has_private_session(self, user_id: int) -> bool:
        return user_id in self.user_clients

    async def save_all_tokens(self):
        tokens_map = {}
        # Gabungkan semua client untuk backup token
        all_active = list(self.global_clients) + list(self.user_clients.values())
        
        for client in all_active:
            if hasattr(client, 'email') and client.email and client.refresh_token:
                tokens_map[client.email] = {
                    'access_token': client.access_token,
                    'refresh_token': client.refresh_token,
                    'email': client.email
                }
        try:
            await database.set_variable('BEATPORT_TOKENS', tokens_map)
        except Exception: pass

    # --- Quality Helpers ---
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatport_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('beatport_qual', self.quality)

beatport_manager = BeatportLoginManager(Config.BEATPORT_ACCOUNTS)
