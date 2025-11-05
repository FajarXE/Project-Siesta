# [FILE BARU: bot/helpers/beatport/api.py]

import aiohttp
import asyncio
from datetime import timedelta, datetime
from bot.logger import LOGGER

# Ini adalah kelas Error kustom kita
class BeatportError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatportError, self).__init__(message)

class BeatportAPI:
    def __init__(self):
        self.API_URL = "https://api.beatport.com/v4/"
        # Client ID dari file Anda
        self.client_id = "Zy2K9Wvy6DkUds7g8s1GNMHfk17E5Ch2BWHlyaGY"
        self.redirect_uri = "seratodjlite://beatport"

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.session = None # Akan menjadi ClientSession aiohttp

    async def _init_session(self):
        """Membuat sesi aiohttp jika belum ada."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={'user-agent': 'libbeatport/v2.8.2'}
            )

    async def close_session(self):
        """Menutup sesi aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, use_access_token: bool = False):
        """Mendapatkan header untuk permintaan."""
        headers = {'user-agent': 'libbeatport/v2.8.2'}
        if use_access_token and self.access_token:
            headers['authorization'] = f'Bearer {self.access_token}'
        return headers

    async def login(self, email: str, password: str):
        """Melakukan alur login OAuth lengkap secara async."""
        await self._init_session()
        
        acc_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/131.0.0.0 Safari/537.36",
        }
        
        # 1. Otorisasi (dapatkan URL referer)
        params_auth = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
        }
        async with self.session.get(f"{self.API_URL}auth/o/authorize/", params=params_auth, headers=acc_headers, allow_redirects=False) as r:
            if r.status != 302:
                raise BeatportError(f"Auth step 1 gagal: {await r.text()}")
            base_url = str(r.url).replace(r.request_info.url.path_qs, '')
            referer = base_url + r.headers['location']

        # 2. Login (kirim email/pass)
        json_login = {"username": email, "password": password}
        async with self.session.post(f"{self.API_URL}auth/login/", json=json_login, headers={**acc_headers, "Referer": referer}) as r:
            if r.status != 200:
                raise BeatportError(f"Auth step 2 (Login) gagal: {await r.text()}")

        # 3. Otorisasi lagi (dapatkan kode)
        async with self.session.get(f"{self.API_URL}auth/o/authorize/", params=params_auth, headers=acc_headers, allow_redirects=False) as r:
            if r.status != 302:
                raise BeatportError(f"Auth step 3 (Get Code) gagal: {await r.text()}")
            code = r.headers['location'].split('code=')[1]

        # 4. Tukarkan kode dengan token
        data_token = {
            "client_id": self.client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        async with self.session.post(f"{self.API_URL}auth/o/token/", data=data_token) as r:
            if r.status != 200:
                raise BeatportError(f"Auth step 4 (Get Token) gagal: {await r.text()}")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.info(f"Beatport: Login berhasil untuk {email}")

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
                LOGGER.error("Beatport: Gagal me-refresh token, mungkin perlu login ulang.")
                raise BeatportError("Gagal me-refresh token")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.debug("Beatport: Token berhasil di-refresh.")

    async def _get(self, endpoint: str, params: dict = None):
        """Fungsi pembantu GET yang aman untuk API."""
        await self._init_session()
        if not params:
            params = {}

        # Cek jika token kedaluwarsa
        if self.expires and datetime.now() > self.expires:
            try:
                await self.refresh()
            except Exception as e:
                raise BeatportError(f"Token kedaluwarsa dan gagal di-refresh: {e}")

        async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(use_access_token=True)) as r:
            if r.status == 401:
                raise BeatportError("Token tidak valid atau kedaluwarsa.")
            if r.status == 403:
                try:
                    detail = (await r.json()).get("detail", "")
                    if "Territory" in detail:
                        raise BeatportError("Region locked (Territory Restricted)")
                except:
                    pass
                raise BeatportError(f"Akses ditolak (403): {await r.text()}")
            
            if r.status != 200:
                raise ConnectionError(f"Beatport API Error {r.status}: {await r.text()}")

            return await r.json()

    # --- Endpoint Katalog (Berdasarkan beatport_api.py) ---

    async def get_account(self):
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
        return await self._get(f'catalog/charts/{chart_id}')

    async def get_chart_tracks(self, chart_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/charts/{chart_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_artist(self, artist_id: str):
        return await self._get(f'catalog/artists/{artist_id}')

    async def get_artist_tracks(self, artist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/artists/{artist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_track_download(self, track_id: str, quality: str):
        # 'quality' bisa "medium", "high", atau "lossless"
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
