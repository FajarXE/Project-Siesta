# [BUAT FILE BARU: bot/helpers/highresaudio/api.py]

import requests
import json
from bs4 import BeautifulSoup
from bot.logger import LOGGER

class HighResAudioApi:
    
    def __init__(self, exception):
        self.API_URL = 'https://streaming.highresaudio.com:8182/vault3/'
        self.STORE_URL = 'https://www.highresaudio.com/'
        self.STREAM_REFERER_URL = 'https://stream-app.highresaudio.com/album/'
        
        self.exception = exception
        self.s = requests.Session()
        # Header User-Agent diambil dari HRA-DL.py
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:67.0) Gecko/20100101 Firefox/67.0"
        })
        
        # Ini akan diisi dengan string JSON mentah setelah login berhasil
        self.user_data_string = None 

    def auth(self, username: str, password: str) -> dict:
        """
        Mencoba login dan menyimpan string JSON user_data mentah.
        Logika dari HRA-DL.py
        """
        LOGGER.info(f"HighResAudio: Mencoba login untuk {username}...")
        try:
            r = self.s.get(f'{self.API_URL}user/login', params={
                'password': password,
                'username': username
            }, timeout=10)

            r.raise_for_status()
            data = r.json()

            if "has_subscription" not in data:
                raise self.exception('Akun tidak memiliki langganan aktif.')
            
            # HRA-DL.py menggunakan r.text (string JSON mentah) sebagai 'userData'
            self.user_data_string = r.text
            
            LOGGER.info(f"HighResAudio: Login berhasil untuk {username}.")
            return data

        except requests.exceptions.RequestException as e:
            LOGGER.error(f"HighResAudio: Gagal login: {e}")
            raise self.exception(f"Gagal login HighResAudio: {e}")
        except Exception as e:
            LOGGER.error(f"HighResAudio: Error saat login: {e}")
            raise self.exception(f"Error login HighResAudio: {e}")

    def get_album_id_from_url(self, url: str) -> str:
        """
        Mengambil (scrape) halaman HTML toko untuk mendapatkan 'data-id' internal.
        Logika dari HRA-DL.py fetchAlbumId()
        """
        try:
            r = self.s.get(url)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            # Temukan tag yang memiliki atribut 'data-id'
            element = soup.find(attrs={"data-id": True})
            
            if not element or not element.get('data-id'):
                raise self.exception('Gagal menemukan data-id dari halaman HTML.')
                
            return element['data-id']
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal scraping album ID: {e}")
            raise self.exception(f'Gagal scraping ID album dari URL: {e}')

    def get_album_metadata(self, album_id: str) -> dict:
        """
        Mengambil metadata album dari API menggunakan album_id dan user_data.
        Logika dari HRA-DL.py fetchMetadata()
        """
        if not self.user_data_string:
            raise self.exception("Klien tidak login (user_data tidak ada).")
            
        try:
            r = self.s.get(f'{self.API_URL}vault/album/', params={
                'album_id': album_id,
                'userData': self.user_data_string 
            })
            r.raise_for_status()
            return r.json()
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal mengambil metadata album: {e}")
            raise self.exception(f'Gagal mengambil metadata album: {e}')

    def get_track_stream(self, url: str, album_id_referer: str) -> requests.Response:
        """
        Menyiapkan dan mengembalikan stream unduhan (requests Response object).
        Logika dari HRA-DL.py fetchTrack()
        """
        headers = {
            "range": "bytes=0-",
            "referer": f"{self.STREAM_REFERER_URL}{album_id_referer}"
        }
        
        try:
            r = self.s.get(url, headers=headers, stream=True, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal memulai stream lagu: {e}")
            raise self.exception(f'Gagal memulai stream lagu: {e}')
            
    def get_booklet_stream(self, url: str) -> requests.Response:
        """
        Mengunduh booklet (tanpa header khusus).
        Logika dari HRA-DL.py fetchBooklet()
        """
        try:
            # Booklet adalah URL lengkap 'https://...'
            r = self.s.get(url, stream=True, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal memulai stream booklet: {e}")
            raise self.exception(f'Gagal memulai stream booklet: {e}')

