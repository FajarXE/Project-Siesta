# [GANTI FILE: bot/helpers/beatsource/manager.py]

import asyncio
import itertools
from bot.logger import LOGGER
from config import Config

try:
    from ..database.mongo_async import database
except (ImportError, ModuleNotFoundError):
    LOGGER.critical("Beatsource Manager: Gagal mengimpor 'database'. Fungsi pemuatan kualitas mungkin gagal.")
    class DummyDatabase:
        async def get_variable(self, *args, **kwargs): return {}
    database = DummyDatabase()

try:
    from .api import BeatsourceAPI
except ImportError:
    LOGGER.critical("Beatsource: Gagal mengimpor 'BeatsourceAPI' dari 'bot/helpers/beatsource/api.py'. File inti tidak ada.")
    class BeatsourceAPI:
        def __init__(self, *args, **kwargs): pass
        async def login(self, *args, **kwargs): raise NotImplementedError("File 'BeatsourceAPI' inti tidak ditemukan.")
        async def close_session(self): pass


class BeatsourceLoginManager:
    """
    Mengelola kumpulan instans klien BeatsourceAPI yang sudah login.
    Juga mengelola pengaturan kualitas default dan per-pengguna.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = [] 
        self._client_cycler = None
        
        # Kualitas default, "medium" adalah yang paling aman
        self.quality = "medium" 
        self.user_data = {} 
        # Cache untuk status langganan agar tidak dicek setiap unduhan
        self.subscription_cache = {} # { client_hash: "pro" / "basic" }

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Beatsource dari Config
        dan memuat pengaturan kualitas default.
        """
        
        try:
            all_settings = await database.get_variable()
            if not all_settings:
                all_settings = {}

            # Baca BEATSOURCE_QUALITY dari DB
            db_quality = all_settings.get('BEATSOURCE_QUALITY')
            
            if db_quality in ["lossless", "high", "medium"]:
                self.quality = db_quality
                LOGGER.info(f"Beatsource Manager: Kualitas default dimuat dari DB: {self.quality}")
            else:
                LOGGER.info(f"Beatsource Manager: Kualitas default DB tidak ada/valid, menggunakan: {self.quality}")
        except Exception as e:
            LOGGER.error(f"Beatsource Manager: Gagal memuat kualitas dari DB: {e}. Menggunakan default: {self.quality}")

        if not self.account_configs:
            LOGGER.warning("Beatsource Manager: Tidak ada akun untuk diinisialisasi.")
            return

        LOGGER.info(f"Beatsource Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Beatsource Manager: Gagal login ke SEMUA akun Beatsource.")
            return

        LOGGER.info(f"Beatsource Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun.")
        self._client_cycler = itertools.cycle(self.clients)
        
        # Pre-cache status langganan
        await self._cache_subscriptions()

    async def _login_task(self, account: dict):
        """Tugas login untuk satu akun."""
        client = BeatsourceAPI()
        try:
            await client.login(
                email=account['email'], 
                password=account['password']
            )
            LOGGER.info(f"Beatsource Manager: Berhasil login ke Akun #{account['id']}")
            return client
        except Exception as e:
            LOGGER.error(f"Beatsource Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            await client.close_session() # Pastikan sesi ditutup
            return None

    async def _cache_subscriptions(self):
        """Mengambil dan menyimpan status langganan untuk semua klien yang login."""
        LOGGER.info(f"Beatsource Manager: Memeriksa status langganan...")
        for client in self.clients:
            try:
                account_data = await client.get_account()
                sub = account_data.get("subscription")
                
                # --- PERBAIKAN LOGGING ---
                # Baris ini akan memberitahu Anda nama langganan yang sebenarnya di log
                LOGGER.info(f"Beatsource Manager: Ditemukan status langganan: '{sub}'")
                # --- AKHIR PERBAIKAN ---

                # --- PERBAIKAN BUG UTAMA ---
                # Mengganti "bp_link_pro" (Beatport) dengan "bs_link_pro" (Beatsource)
                if sub == "bs_link_pro":
                # --- AKHIR PERBAIKAN ---
                    self.subscription_cache[client] = "pro"
                    LOGGER.info(" -> Ditemukan langganan 'Pro'. Kualitas Lossless/High diaktifkan.")
                else:
                    self.subscription_cache[client] = "basic"
                    LOGGER.info(f" -> Langganan '{sub}' bukan 'Pro'. Kualitas dibatasi ke 'Medium' (128k AAC).")
            except Exception as e:
                LOGGER.warning(f"Beatsource Manager: Gagal memeriksa langganan untuk satu klien: {e}")
                self.subscription_cache[client] = "basic" # Asumsikan basic jika gagal

    def get_client_and_sub(self) -> (BeatsourceAPI | None, str):
        """
        Mendapatkan klien berikutnya dari kumpulan (round-robin) dan status langganannya.
        """
        if not self._client_cycler:
            LOGGER.error("Beatsource Manager: Tidak ada klien yang tersedia.")
            return None, "basic"
        
        try:
            client = next(self._client_cycler)
            sub_status = self.subscription_cache.get(client, "basic") # Default ke basic
            return client, sub_status
        except StopIteration:
            LOGGER.error("Beatsource Manager: Kumpulan klien kosong.")
            return None, "basic"
    
    async def setup_quality(self, user_id: int, qual: str = None):
        """Mengatur cache kualitas untuk pengguna tertentu."""
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        if qual in ["lossless", "high", "medium"]:
            self.user_data[user_id]['beatsource_qual'] = qual
            LOGGER.debug(f"Beatsource Manager: Mengatur kualitas user {user_id} ke {qual}")

    def get_user_quality(self, user_id: int) -> str:
        """Mendapatkan kualitas untuk pengguna, fallback ke default."""
        user_qual = self.user_data.get(user_id, {}).get('beatsource_qual')
        if user_qual in ["lossless", "high", "medium"]:
            return user_qual
        return self.quality 

# Buat instance global
beatsource_manager = BeatsourceLoginManager(Config.BEATSOURCE_ACCOUNTS)
