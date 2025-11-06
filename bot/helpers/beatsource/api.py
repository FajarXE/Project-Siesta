# [FILE BARU: bot/helpers/beatsource/api.py]

import aiohttp
import asyncio
from datetime import timedelta, datetime
from bot.logger import LOGGER
from urllib.parse import urlparse, parse_qs

# Ini adalah kelas Error kustom kita
class BeatsourceError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatsourceError, self).__init__(message)

class BeatsourceAPI:
    def __init__(self):
        self.API_URL = "https://api.beatsource.com/v4/"
        # Client ID dari file beatsource_api.py
        self.client_id = "ryZ8LuyQVPqbK2mBX2Hwt4qSMtnWuTYSqBPO92yQ"
        # (redirect_uri tidak digunakan dalam alur login ini)

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.session = None # Akan menjadi ClientSession aiohttp

    async def _init_session(self):
        """Membuat sesi aiohttp jika belum ada."""
        if self.session is None or self.session.closed:
            # Kita perlu cookie jar untuk alur login 3 langkah
            self.session = aiohttp.ClientSession(
                headers={'user-agent': 'libbeatsource/v2.8.2'},
                cookie_jar=aiohttp.CookieJar(unsafe=True)
            )

    async def close_session(self):
        """Menutup sesi aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    def _get_headers(self, use_access_token: bool = False):
        """Mendapatkan header untuk permintaan."""
        headers = {'user-agent': 'libbeatsource/v2.8.2'}
        if use_access_token and self.access_token:
            headers['authorization'] = f'Bearer {self.access_token}'
        return headers

    async def login(self, email: str, password: str):
        """Melakukan alur login OAuth 3 langkah Beatsource secara async."""
        await self._init_session()
        
        login_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        }
        
        try:
            # --- Langkah 1: Login (Email/Pass) untuk mendapatkan cookie sessionid ---
            login_url = f"{self.API_URL}auth/login/"
            login_payload = {"username": email, "password": password}
            
            async with self.session.post(login_url, json=login_payload, headers=login_headers) as r_login:
                if r_login.status != 200:
                    try:
                        resp_json = await r_login.json()
                        if "non_field_errors" in resp_json:
                            raise BeatsourceError(f"Login gagal: {resp_json['non_field_errors'][0]}")
                    except Exception:
                        pass # Jatuh ke error umum
                    raise BeatsourceError(f"Login Langkah 1 gagal ({r_login.status}): {await r_login.text()}")

            # Verifikasi cookie sessionid
            session_id_cookie = self.session.cookie_jar.filter_cookies(self.API_URL).get('sessionid')
            if not session_id_cookie:
                raise BeatsourceError("Tidak dapat menemukan cookie sessionid setelah login.")

            # --- Langkah 2: Otorisasi (via cookie) untuk mendapatkan 'code' ---
            auth_url = f"{self.API_URL}auth/o/authorize/"
            auth_params = {
                "client_id": self.client_id,
                "response_type": "code",
            }
            
            async with self.session.get(auth_url, params=auth_params, headers=login_headers, allow_redirects=False) as r_auth:
                if r_auth.status != 302: # Harapannya redirect
                    raise BeatsourceError(f"Otorisasi Langkah 2 gagal ({r_auth.status}), harapannya 302. Respon: {await r_auth.text()}")

                redirect_location = r_auth.headers.get('Location')
                if not redirect_location:
                    raise BeatsourceError("Otorisasi Langkah 2 tidak mengembalikan header Lokasi.")
                
                # Parse 'code' dari URL redirect
                try:
                    parsed_url = urlparse(redirect_location)
                    query_params = parse_qs(parsed_url.query)
                    code = query_params.get('code', [None])[0]
                except Exception as e:
                    raise BeatsourceError(f"Gagal mem-parse code otorisasi: {e}")
                
                if not code:
                    raise BeatsourceError(f"Tidak dapat mengekstrak code otorisasi dari Lokasi redirect.")

            # --- Langkah 3: Tukar 'code' dengan token ---
            token_url = f"{self.API_URL}auth/o/token/"
            token_payload = {
                "client_id": self.client_id,
                "code": code,
                "grant_type": "authorization_code",
            }
            
            # Gunakan 'data' (form-encoded), bukan 'json'
            async with self.session.post(token_url, data=token_payload, headers=login_headers) as r_token:
                if r_token.status != 200:
                    raise BeatsourceError(f"Penukaran Token Langkah 3 gagal ({r_token.status}): {await r_token.text()}")
                
                resp_json = await r_token.json()
                self.access_token = resp_json['access_token']
                self.refresh_token = resp_json['refresh_token']
                self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
                LOGGER.info(f"Beatsource: Login berhasil untuk {email}")

        except Exception as e:
            # Pastikan sesi ditutup jika login gagal
            await self.close_session()
            raise e


    async def refresh(self):
        """Me-refresh access token."""
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data) as r:
            if r.status != 200:
                LOGGER.error("Beatsource: Gagal me-refresh token, mungkin perlu login ulang.")
                raise BeatsourceError("Gagal me-refresh token")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            # Token refresh itu sendiri mungkin diperbarui
            self.refresh_token = resp_json.get('refresh_token', self.refresh_token)
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.debug("Beatsource: Token berhasil di-refresh.")

    async def _get(self, endpoint: str, params: dict = None):
        """Fungsi pembantu GET yang aman untuk API."""
        await self._init_session()
        if not params:
            params = {}

        if self.expires and datetime.now() > self.expires:
            try:
                await self.refresh()
            except Exception as e:
                raise BeatsourceError(f"Token kedaluwarsa dan gagal di-refresh: {e}")

        async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(use_access_token=True)) as r:
            if r.status == 401:
                raise BeatsourceError("Token tidak valid atau kedaluwarsa.")
            if r.status == 403:
                try:
                    detail = (await r.json()).get("detail", "")
                    if "Territory" in detail:
                        raise BeatsourceError("Region locked (Territory Restricted)")
                except:
                    pass
                raise BeatsourceError(f"Akses ditolak (403): {await r.text()}")
            
            if r.status == 404:
                raise BeatsourceError(f"Item tidak ditemukan (404)")
            
            if r.status != 200:
                raise ConnectionError(f"Beatsource API Error {r.status}: {await r.text()}")

            return await r.json()

    # --- Endpoint Katalog (Sama seperti Beatport/Beatsource) ---

    async def get_account(self):
        """Digunakan untuk memeriksa status langganan."""
        return await self._get('auth/o/introspect')

    async def get_track(self, track_id: str):
        return await self._get(f'catalog/tracks/{track_id}')

    async def get_release(self, release_id: str):
        return await self._get(f'catalog/releases/{release_id}')

    async def get_release_tracks(self, release_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/releases/{release_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_playlist(self, playlist_id: str):
        return await self._get(f'catalog/playlists/{playlist_id}')

    async def get_playlist_tracks(self, playlist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/playlists/{playlist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_chart(self, chart_id: str):
        """Endpoint fallback untuk playlist."""
        return await self._get(f'catalog/charts/{chart_id}')

    async def get_chart_tracks(self, chart_id: str, page: int = 1, per_page: int = 100):
        """Endpoint fallback untuk track playlist."""
        return await self._get(f'catalog/charts/{chart_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_artist(self, artist_id: str):
        return await self._get(f'catalog/artists/{artist_id}')

    async def get_artist_tracks(self, artist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/artists/{artist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_track_download(self, track_id: str, quality: str):
        """Kualitas bisa "medium", "high", atau "lossless"."""
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
