import os
import json
import asyncio
import logging
from config import Config
from .spotify_api import SpotifyAPI

LOGGER = logging.getLogger("SpotifyManager")

class SpotifyManager:
    def __init__(self):
        self.client = None
        self.authenticated = False
        # Path kredensial
        self.credentials_path = os.path.join(os.getcwd(), "bot", "config", "spotify", "credentials.json")

    async def initialize_clients(self):
        """
        Dijalankan saat startup. 
        [UPDATED] Kompatibel dengan MongoDB (Tidak memaksa file fisik harus ada).
        """
        LOGGER.info("Spotify: Menginisialisasi...")
        
        # 1. Cek ENV (Legacy Support - Jika user lupa hapus ENV)
        # Gunakan getattr untuk safety jika config tidak punya atribut tersebut
        env_creds = getattr(Config, 'SPOTIFY_CREDENTIALS_JSON', None)
        
        if env_creds:
            LOGGER.info("Spotify: Kredensial ditemukan di ENV Variables.")
            try:
                os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
                with open(self.credentials_path, "w") as f:
                    f.write(env_creds)
            except Exception as e:
                LOGGER.warning(f"Gagal menulis ENV ke file (Akan mencoba MongoDB): {e}")
        
        # 2. [LOGIKA BARU] Cek File Fisik (Hanya Info, BUKAN Syarat Wajib)
        if not os.path.exists(self.credentials_path):
            LOGGER.info(f"File kredensial fisik belum ada. Bot akan mencoba menarik data dari MongoDB via API...")
            # KITA HAPUS 'return' DISINI AGAR PROSES TIDAK BERHENTI

        # 3. Inisialisasi Client
        try:
            # Jalankan di thread terpisah agar tidak memblokir async loop saat startup
            await asyncio.to_thread(self._sync_init)
            
            # Cek apakah sesi berhasil dibuat
            # Kita cek librespot_session karena itu indikator utama login sukses
            if self.client and self.client.librespot_session:
                self.authenticated = True
                LOGGER.info("✅ Spotify: Login Berhasil (Siap Download)!")
            else:
                LOGGER.warning("⚠️ Spotify: Login belum aktif. Silakan jalankan /spotify_login jika download gagal.")
                # Kita set True sementara agar bot tidak menolak perintah download, 
                # karena kadang API butuh waktu untuk connect.
                self.authenticated = True 
        except Exception as e:
            LOGGER.error(f"❌ Spotify: Error Init -> {e}")
            # Tetap set authenticated True agar user bisa mencoba command /spotify_login lagi tanpa restart
            self.authenticated = True

    def _sync_init(self):
        """Fungsi sinkronus untuk init API"""
        config = {
            "username": "BotUser",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "credentials_location": self.credentials_path 
        }
        
        # Inisialisasi API
        # Saat kelas ini dipanggil, dia akan otomatis menjalankan _load_credentials_and_init_session
        # yang sudah kita modifikasi untuk membaca MongoDB.
        self.client = SpotifyAPI(config=config)
        
        # Panggil fungsi autentikasi eksplisit jika ada
        if hasattr(self.client, 'authenticate_stream_api'):
            self.client.authenticate_stream_api()
        elif hasattr(self.client, '_load_credentials_and_init_session'):
            self.client._load_credentials_and_init_session()

    def get_client(self):
        # Selalu kembalikan client jika objeknya ada
        # Biarkan spotify_api.py yang menangani error jika token mati
        if self.client:
            return self.client
        return None
    
    async def shutdown(self):
        pass

# Instance Global
spotify_manager = SpotifyManager()
