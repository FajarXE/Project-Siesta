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
        self.credentials_path = os.path.join(os.getcwd(), "config", "spotify", "credentials.json")

    async def initialize(self):
        """
        Dijalankan saat startup. Mengecek ENV Render atau File Lokal.
        """
        LOGGER.info("Spotify: Menginisialisasi...")
        
        # 1. Cek apakah ada Kredensial di ENV (Prioritas untuk Render)
        env_creds = Config.SPOTIFY_CREDENTIALS_JSON
        
        if env_creds:
            LOGGER.info("Spotify: Kredensial ditemukan di ENV Variables.")
            # Tulis ke file fisik karena library spotify_api.py membacanya dari file
            os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
            with open(self.credentials_path, "w") as f:
                f.write(env_creds)
        
        # 2. Cek apakah file fisik ada (jika tidak pakai ENV/Local run)
        if not os.path.exists(self.credentials_path):
            LOGGER.warning("Spotify: Tidak ada kredensial. Jalankan /spotify_login nanti.")
            return

        # 3. Inisialisasi Client
        try:
            # Jalankan di thread terpisah agar tidak memblokir async loop saat startup
            await asyncio.to_thread(self._sync_init)
            
            if self.client and self.client.librespot_session:
                self.authenticated = True
                LOGGER.info("Spotify: Login Berhasil!")
            else:
                LOGGER.warning("Spotify: Gagal login (Token Expired?).")
        except Exception as e:
            LOGGER.error(f"Spotify: Error Init -> {e}")

    def _sync_init(self):
        """Fungsi sinkronus untuk init API"""
        config = {
            "username": "BotUser",
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET
        }
        self.client = SpotifyAPI(config=config)
        # authenticate_stream_api akan mencoba me-refresh token jika expired
        self.client.authenticate_stream_api()

    def get_client(self):
        if self.authenticated and self.client:
            return self.client
        return None

# Instance Global
spotify_manager = SpotifyManager()
