# [GANTI FILE: bot/helpers/nugs/manager.py]

import asyncio
import itertools
from datetime import datetime

from bot.logger import LOGGER
from config import Config

# Impor kelas-kelas inti dari file API Nugs Anda
try:
    from .nugs_api import NugsMobileSession, NugsApi, NugsNotAvailableError
except ImportError:
    LOGGER.critical("Nugs Manager: Gagal mengimpor 'NugsApi' atau 'NugsMobileSession' dari 'bot/helpers/nugs/nugs_api.py'.")
    # Definisikan kelas dummy jika impor gagal
    class NugsMobileSession:
        def __init__(self, *args, **kwargs): pass
        def auth(self, *args, **kwargs): raise NotImplementedError("File NugsApi tidak ditemukan.")
        def get_subscription(self, *args, **kwargs): raise NotImplementedError("File NugsApi tidak ditemukan.")
    class NugsApi:
        def __init__(self, *args, **kwargs): pass
        # --- Tambahkan stub close_session ---
        def close_session(self): pass
        # --- Akhir Tambahan ---
    class NugsNotAvailableError(Exception): pass

# Pengecualian kustom agar konsisten dengan manajer lain
class NugsError(Exception):
    pass

class NugsLoginManager:
    """
    Mengelola kumpulan instans klien NugsApi yang sudah login.
    """
    def __init__(self, account_configs: list):
        self.account_configs = account_configs
        self.clients = []  # List untuk menyimpan instance NugsApi yang berhasil login
        self._client_cycler = None
        
        # Kunci-kunci ini di-hardcode di interface.py
        self.client_id = 'Eg7HuH873H65r5rt325UytR5429'
        self.dev_key = 'x7f54tgbdyc64y656thy47er4'

    async def initialize_clients(self):
        """
        Mencoba login ke semua akun Nugs.net dari Config.
        """
        if not self.account_configs:
            LOGGER.warning("Nugs Manager: Tidak ada akun NUGS_ACCOUNTS untuk diinisialisasi di Config.")
            return

        LOGGER.info(f"Nugs Manager: Menginisialisasi {len(self.account_configs)} akun...")
        tasks = []
        for account in self.account_configs:
            tasks.append(self._login_task(account))
        
        results = await asyncio.gather(*tasks)
        
        # Klien yang berhasil adalah instance NugsApi
        self.clients = [client for client in results if client is not None]
        
        if not self.clients:
            LOGGER.error("Nugs Manager: Gagal login ke SEMUA akun Nugs.net.")
            return

        LOGGER.info(f"Nugs Manager: Berhasil login ke {len(self.clients)} dari {len(self.account_configs)} akun Nugs.")
        self._client_cycler = itertools.cycle(self.clients)

    async def _login_task(self, account: dict):
        """
        Tugas login untuk satu akun (menggunakan asyncio.to_thread karena berbasis 'requests').
        """
        # --- Tambahan: Variabel klien untuk cleanup ---
        api_client = None
        session = None
        # --- Akhir Tambahan ---
        try:
            email = account['email']
            password = account['password']
            
            if not email or not password:
                LOGGER.error(f"Nugs Akun #{account['id']}: Email atau password tidak ada.")
                return None

            # 1. Buat Sesi Seluler (untuk login)
            session = NugsMobileSession(self.client_id, self.dev_key)
            
            # 2. Login (ini adalah operasi blocking, jalankan di thread)
            LOGGER.debug(f"Nugs Manager: Mencoba login ke Akun #{account['id']}...")
            await asyncio.to_thread(session.auth, email, password)
            
            # 3. Verifikasi Langganan (Subscription)
            sub = await asyncio.to_thread(session.get_subscription)
            current_time = int(datetime.now().timestamp())
            
            if sub.end_stamp < current_time:
                raise NugsError(f"Langganan untuk Akun #{account['id']} telah berakhir pada {datetime.fromtimestamp(sub.end_stamp)}")
            
            LOGGER.info(f"Nugs Manager: Berhasil login & verifikasi langganan Akun #{account['id']}.")

            # 4. Buat Klien API utama dengan sesi yang sudah login
            api_client = NugsApi(session)
            
            # Simpan data langganan ke klien, karena ini diperlukan untuk get_stream
            api_client.subscription_details = sub
            
            return api_client
            
        except Exception as e:
            LOGGER.error(f"Nugs Manager: Gagal login ke Akun #{account['id']}. Error: {e}")
            # --- Tambahan: Panggil close_session jika login gagal ---
            if api_client and hasattr(api_client, 'close_session'):
                await asyncio.to_thread(api_client.close_session)
            # --- Akhir Tambahan ---
            return None

    def get_client(self) -> NugsApi | None:
        """
        Mengembalikan klien NugsApi yang sudah login secara bergiliran.
        """
        if not self._client_cycler:
            LOGGER.error("Nugs Manager: Tidak ada klien yang tersedia.")
            return None
        
        try:
            return next(self._client_cycler)
        except StopIteration:
            LOGGER.error("Nugs Manager: Kumpulan klien kosong.")
            return None

    # --- TAMBAHAN BARU: Metode Shutdown ---
    async def shutdown(self):
        """Menutup semua sesi klien NugsApi (requests) yang dikelola."""
        LOGGER.info(f"Nugs Manager: Memulai shutdown... Menutup {len(self.clients)} sesi klien 'requests'.")
        tasks = []
        for client in self.clients:
            if hasattr(client, 'close_session'):
                # Panggil 'close_session' (sinkron) di thread terpisah
                tasks.append(asyncio.to_thread(client.close_session))
        
        # Jalankan semua tugas penutupan secara bersamaan
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            LOGGER.error(f"Nugs Manager: Terjadi error saat shutdown: {e}")
            
        self.clients = []
        self._client_cycler = None
        LOGGER.info("Nugs Manager: Semua sesi klien 'requests' telah ditutup.")
    # --- AKHIR TAMBAHAN ---


# Buat instance global yang akan diimpor oleh file lain
nugs_manager = NugsLoginManager(Config.NUGS_ACCOUNTS)
