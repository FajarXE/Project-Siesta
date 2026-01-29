# [GANTI FILE: bot/helpers/beatsource/manager.py]

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
        class MockClient:
            class MockUsers:
                async def find(self, *args, **kwargs): return self
                async def to_list(self, *args, **kwargs): return []
            users = MockUsers()
        client = MockClient()
    database = DummyDatabase()

try:
    from .api import BeatsourceAPI
except ImportError:
    LOGGER.critical("Beatsource: API Error.")
    class BeatsourceAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("API Error")
        async def close_session(self): pass


class BeatsourceLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        self.quality = "medium" 
        self.user_data = {} 
        self.subscription_cache = {} 

    async def initialize_clients(self):
        saved_tokens = {}
        try:
            all_settings = await database.get_variable() or {}
            db_quality = all_settings.get('BEATSOURCE_QUALITY')
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
            saved_tokens = all_settings.get('BEATSOURCE_TOKENS', {})
        except Exception: pass

        try:
            all_users = await database.client.users.find({}).to_list(None)
            for u in all_users:
                if u.get('beatsource_qual'): 
                    await self.setup_quality(u['_id'], u['beatsource_qual'])
        except: pass

        if not self.account_configs: return

        LOGGER.info(f"Beatsource Manager: Init {len(self.account_configs)} accounts...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account, saved_tokens.get(account['email'])))
        
        results = await asyncio.gather(*tasks)
        self.clients = [c for c in results if c]
        
        if self.clients:
            LOGGER.info(f"Beatsource Manager: {len(self.clients)} clients ready.")
            self._client_cycler = itertools.cycle(self.clients)
            await self.save_all_tokens()
            await self._cache_subscriptions()

    async def _login_task(self, account: dict, saved_token: dict = None):
        client = BeatsourceAPI()
        email, password = account['email'], account['password']
        
        # --- TAMBAHAN PROXY ---
        proxy = account.get('proxy')
        if proxy:
            client.proxy = proxy
        # ----------------------

        if saved_token and saved_token.get('refresh_token'):
            try:
                saved_token['email'] = email
                await client.load_session(saved_token)
                await client.refresh()
                return client
            except Exception: pass

        try:
            await client.login(email=email, password=password)
            return client
        except Exception as e:
            LOGGER.error(f"Beatsource Login Failed {email}: {e}")
            await client.close_session()
            return None

    async def save_all_tokens(self):
        if not self.clients: return
        try:
            tokens_map = {}
            for client in self.clients:
                if hasattr(client, 'email') and client.email and client.refresh_token:
                    tokens_map[client.email] = {
                        'access_token': client.access_token,
                        'refresh_token': client.refresh_token,
                        'email': client.email
                    }
            
            await database.set_variable('BEATSOURCE_TOKENS', tokens_map)
            LOGGER.info("Beatsource Manager: Tokens saved.")
            
        except Exception as e:
            LOGGER.error(f"Beatsource Manager: Gagal menyimpan token: {e}")

    async def _cache_subscriptions(self):
        for client in self.clients:
            try:
                acc = await client.get_account()
                self.subscription_cache[client] = "pro" if acc.get("subscription") == "bsrc_link_pro_plus" else "basic"
            except: self.subscription_cache[client] = "basic"

    def get_client_and_sub(self) -> (BeatsourceAPI | None, str):
        if not self._client_cycler: return None, "basic"
        try:
            client = next(self._client_cycler)
            return client, self.subscription_cache.get(client, "basic")
        except: return None, "basic"
    
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatsource_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('beatsource_qual', self.quality)

    async def shutdown(self):
        await self.save_all_tokens()
        tasks = [c.close_session() for c in self.clients if hasattr(c, 'close_session')]
        if tasks: await asyncio.gather(*tasks)
        self.clients = []

beatsource_manager = BeatsourceLoginManager(Config.BEATSOURCE_ACCOUNTS)
