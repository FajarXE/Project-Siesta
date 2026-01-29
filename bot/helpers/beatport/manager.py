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
    from .api import BeatportAPI
except ImportError:
    LOGGER.critical("Beatport: Gagal mengimpor 'BeatportAPI'.")
    class BeatportAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("API Error")
        async def close_session(self): pass


class BeatportLoginManager:
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        self.quality = "lossless" 
        self.user_data = {} 

    async def initialize_clients(self):
        saved_tokens = {}
        try:
            all_settings = await database.get_variable() 
            if not all_settings: all_settings = {}
            
            db_quality = all_settings.get('BEATPORT_QUALITY')
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
            
            saved_tokens = all_settings.get('BEATPORT_TOKENS', {})
        except Exception: pass

        if not self.account_configs: return

        LOGGER.info(f"Beatport Manager: Init {len(self.account_configs)} accounts...")
        tasks = []
        for account in self.account_configs:
            token_data = saved_tokens.get(account['email'])
            tasks.append(self._login_task(account, token_data))
        
        results = await asyncio.gather(*tasks)
        self.clients = [c for c in results if c]
        
        if self.clients:
            LOGGER.info(f"Beatport Manager: {len(self.clients)} clients ready.")
            self._client_cycler = itertools.cycle(self.clients)
            await self.save_all_tokens()

    async def _login_task(self, account: dict, saved_token: dict = None):
        client = BeatportAPI()
        email, password = account['email'], account['password']
        
        # --- TAMBAHAN PROXY ---
        # Set proxy ke instance client jika tersedia di config akun
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
            LOGGER.error(f"Beatport Login Failed {email}: {e}")
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
            
            await database.set_variable('BEATPORT_TOKENS', tokens_map)
            LOGGER.info("Beatport Manager: Tokens saved.")
            
        except Exception as e:
            LOGGER.error(f"Beatport Manager: Gagal menyimpan token: {e}")

    def get_client(self) -> BeatportAPI | None:
        if not self._client_cycler: return None
        try: return next(self._client_cycler)
        except: return None
    
    async def setup_quality(self, user_id: int, qual: str = None):
        if user_id not in self.user_data: self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatport_qual'] = qual

    def get_user_quality(self, user_id: int) -> str:
        return self.user_data.get(user_id, {}).get('beatport_qual', self.quality)

    async def shutdown(self):
        await self.save_all_tokens()
        tasks = [c.close_session() for c in self.clients if hasattr(c, 'close_session')]
        if tasks: await asyncio.gather(*tasks)
        self.clients = []

beatport_manager = BeatportLoginManager(Config.BEATPORT_ACCOUNTS)
