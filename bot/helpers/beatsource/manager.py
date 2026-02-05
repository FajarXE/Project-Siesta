# [GANTI SELURUH FILE: bot/helpers/beatsource/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Beatsource Manager: No Database.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
        async def set_variable(self, *args, **kwargs): pass
    database = DummyDatabase()

# [PERBAIKAN] Langsung import tanpa try-except.
# Agar jika api.py error (syntax/dependency), kita langsung tahu.
from .api import BeatsourceAPI, BeatsourceError

class BeatsourceLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        
        # GLOBAL CLIENTS (Dari .env)
        self.global_clients = [] 
        self._global_cycler = None
        
        # PRIVATE CLIENTS (Dari DB)
        self.user_clients = {} 
        
        self.quality = "medium" 
        self.user_data = {} 
        self.subscription_cache = {} 

    # --- PROPERTY KOMPATIBILITAS ---
    @property
    def clients(self):
        return self.global_clients + list(self.user_clients.values())

    async def initialize_clients(self):
        saved_tokens = {}
        user_sessions = {}
        
        try:
            all_settings = await database.get_variable() or {}
            
            # Load Quality
            db_quality = all_settings.get('BEATSOURCE_QUALITY')
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
            
            # Load Tokens & Sessions
            saved_tokens = all_settings.get('BEATSOURCE_TOKENS', {})
            user_sessions = all_settings.get('BEATSOURCE_USER_SESSIONS', {})
            
            # Pastikan key user_id adalah integer
            user_sessions = {int(k): v for k, v in user_sessions.items() if str(k).isdigit()}
            
        except Exception: pass

        # Load User Quality Preferences
        try:
            if hasattr(database, 'client'):
                # Pastikan collection ada sebelum query
                if 'users' in await database.client.list_collection_names():
                    all_users = await database.client.users.find({}).to_list(None)
                    for u in all_users:
                        if u.get('beatsource_qual'): 
                            await self.setup_quality(u['_id'], u['beatsource_qual'])
        except: pass

        # 1. INIT GLOBAL CLIENTS
        self.global_clients = []
        tasks_env = []
        
        if self.account_configs:
            LOGGER.info(f"Beatsource Manager: Loading {len(self.account_configs)} global accounts...")
            for account in self.account_configs:
                tasks_env.append(self._login_task(account, saved_tokens.get(account['email'])))
            
            results_env = await asyncio.gather(*tasks_env)
            self.global_clients = [c for c in results_env if c]
            
            if self.global_clients:
                self._global_cycler = itertools.cycle(self.global_clients)

        # 2. INIT PRIVATE USER CLIENTS
        self.user_clients = {}
        tasks_user = []
        user_ids = []
        
        if user_sessions:
            LOGGER.info(f"Beatsource Manager: Loading {len(user_sessions)} private user accounts...")
            for uid, account in user_sessions.items():
                tasks_user.append(self._login_task(account, saved_tokens.get(account['email'])))
                user_ids.append(uid)
            
            results_user = await asyncio.gather(*tasks_user)
            
            for uid, client in zip(user_ids, results_user):
                if client:
                    self.user_clients[uid] = client
                    client.owner_id = uid

        LOGGER.info(f"Beatsource Manager Ready. Global: {len(self.global_clients)}, Private: {len(self.user_clients)}")
        
        await self.save_all_tokens()
        await self._cache_subscriptions()

    async def _login_task(self, account: dict, saved_token: dict = None):
        client = BeatsourceAPI()
        email, password = account['email'], account['password']
        
        # Proxy Setup
        proxy = account.get('proxy')
        if proxy:
            client.proxy = proxy

        # 1. Coba Token (Refresh)
        if saved_token and saved_token.get('refresh_token'):
            try:
                saved_token['email'] = email
                await client.load_session(saved_token)
                await client.refresh()
                return client
            except Exception: 
                # Token mati, lanjut ke login password
                pass

        # 2. Coba Password
        try:
            await client.login(email=email, password=password)
            return client
        except Exception as e:
            LOGGER.error(f"Beatsource Login Failed {email}: {e}")
            await client.close_session()
            return None

    # --- USER MANAGEMENT ---

    async def add_user_account(self, user_id: int, email, password):
        """Login akun pribadi untuk User ID tertentu."""
        temp_client = BeatsourceAPI()
        
        # Coba login
        try:
            await temp_client.login(email, password)
        except Exception as e:
            LOGGER.error(f"Gagal login akun user {user_id}: {e}")
            await temp_client.close_session()
            raise e

        temp_client.owner_id = user_id
        
        # Cleanup sesi lama jika ada
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
        
        self.user_clients[user_id] = temp_client
        
        # Simpan ke DB
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATSOURCE_USER_SESSIONS', {})
        user_sessions[str(user_id)] = {"email": email, "password": password}
        
        await database.set_variable('BEATSOURCE_USER_SESSIONS', user_sessions)
        await self.save_all_tokens()
        await self._cache_subscriptions() 
        return True

    async def remove_user_account(self, user_id: int):
        """Hapus sesi pribadi user."""
        if user_id in self.user_clients:
            await self.user_clients[user_id].close_session()
            del self.user_clients[user_id]
        
        all_settings = await database.get_variable() or {}
        user_sessions = all_settings.get('BEATSOURCE_USER_SESSIONS', {})
        
        if str(user_id) in user_sessions:
            del user_sessions[str(user_id)]
            await database.set_variable('BEATSOURCE_USER_SESSIONS', user_sessions)
            return True
        return False

    def get_client(self, user_id: int = None) -> BeatsourceAPI | None:
        """
        Prioritas: Private Client -> Global Client
        """
        if user_id and user_id in self.user_clients:
            return self.user_clients[user_id]
            
        if self._global_cycler:
            try: return next(self._global_cycler)
            except: pass
        return None
    
    def has_private_session(self, user_id: int) -> bool:
        return user_id in self.user_clients

    async def save_all_tokens(self):
        tokens_map = {}
        all_active = list(self.global_clients) + list(self.user_clients.values())
        
        for client in all_active:
            if hasattr(client, 'email') and client.email and client.refresh_token:
                tokens_map[client.email] = {
                    'access_token': client.access_token,
                    'refresh_token': client.refresh_token,
                    'email': client.email
                }
        try:
            await database.set_variable('BEATSOURCE_TOKENS', tokens_map)
        except Exception: pass

    async def _cache_subscriptions(self):
        """Cache status langganan untuk menentukan kualitas audio maksimal."""
        all_active = list(self.global_clients) + list(self.user_clients.values())
        for client in all_active:
            try:
                acc = await client.get_account()
                # Langganan 'bsrc_link_pro_plus' biasanya mendukung lossless/high
                self.subscription_cache[client] = "pro" if acc.get("subscription") == "bsrc_link_pro_plus" else "basic"
            except: 
                self.subscription_cache[client] = "basic"

    def get_client_and_sub(self, user_id: int = None) -> tuple[BeatsourceAPI | None, str]:
        """Helper untuk mendapatkan client dan tipe langganannya."""
        client = self.get_client(user_id)
        if not client: return None, "basic"
        return client, self.subscription_cache.get(client, "basic")
    
    # --- Quality Helpers ---
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatsource_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('beatsource_qual', self.quality)

    async def shutdown(self):
        await self.save_all_tokens()
        all_active = list(self.global_clients) + list(self.user_clients.values())
        tasks = [c.close_session() for c in all_active if hasattr(c, 'close_session')]
        if tasks: await asyncio.gather(*tasks)
        self.global_clients = []
        self.user_clients = {}

beatsource_manager = BeatsourceLoginManager(Config.BEATSOURCE_ACCOUNTS)
