# [GANTI SELURUH FILE: bot/helpers/beatport/api.py]

import aiohttp
import asyncio
from datetime import timedelta, datetime
from bot.logger import LOGGER

# --- Cek Library Proxy ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None
# -------------------------

# Konstanta User-Agent
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

class BeatportError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatportError, self).__init__(message)

class BeatportAPI:
    def __init__(self):
        self.API_URL = "https://api.beatport.com/v4/"
        self.client_id = "Zy2K9Wvy6DkUds7g8s1GNMHfk17E5Ch2BWHlyaGY"
        self.redirect_uri = "seratodjlite://beatport"

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.email = None
        self.password_cache = None
        self.proxy = None
        self.session = None 

    async def _init_session(self):
        """Membuat sesi aiohttp dengan dukungan Proxy (Auto-fix socks5h)."""
        if self.session is None or self.session.closed:
            connector = None
            
            # --- LOGIKA KONEKTOR PROXY ---
            if self.proxy:
                if ProxyConnector:
                    try:
                        # FIX: Handle socks5h manual jika library menolak skemanya
                        proxy_url = self.proxy
                        use_rdns = False
                        
                        if proxy_url.startswith("socks5h://"):
                            proxy_url = proxy_url.replace("socks5h://", "socks5://")
                            use_rdns = True
                        
                        connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                        LOGGER.debug(f"BeatportAPI: Menggunakan Proxy untuk {self.email} (RDNS: {use_rdns})")
                    except Exception as e:
                        LOGGER.error(f"BeatportAPI: Gagal menginisialisasi Proxy Connector: {e}")
                else:
                    LOGGER.error("BeatportAPI: Proxy diset tapi 'aiohttp_socks' belum diinstall.")
            # -----------------------------

            self.session = aiohttp.ClientSession(
                headers={'user-agent': USER_AGENT},
                connector=connector
            )

    async def close_session(self):
        """Menutup sesi aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, use_access_token: bool = False):
        headers = {'user-agent': USER_AGENT}
        if use_access_token and self.access_token:
            headers['authorization'] = f'Bearer {self.access_token}'
        return headers

    async def load_session(self, token_data: dict):
        await self._init_session()
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')
        self.email = token_data.get('email')
        self.expires = datetime.now() - timedelta(seconds=10)
        LOGGER.debug(f"BeatportAPI: Sesi dimuat untuk {self.email} (Pending Refresh)")

    async def login(self, email: str, password: str):
        self.email = email
        self.password_cache = password
        await self._init_session()
        
        acc_headers = {"User-Agent": USER_AGENT}
        
        # 1. Otorisasi
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

        # 2. Login
        json_login = {"username": email, "password": password}
        async with self.session.post(f"{self.API_URL}auth/login/", json=json_login, headers={**acc_headers, "Referer": referer}) as r:
            if r.status != 200:
                raise BeatportError(f"Auth step 2 (Login) gagal: {await r.text()}")

        # 3. Otorisasi lagi
        async with self.session.get(f"{self.API_URL}auth/o/authorize/", params=params_auth, headers=acc_headers, allow_redirects=False) as r:
            if r.status != 302:
                raise BeatportError(f"Auth step 3 (Get Code) gagal: {await r.text()}")
            code = r.headers['location'].split('code=')[1]

        # 4. Tukar kode dengan token
        data_token = {
            "client_id": self.client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        async with self.session.post(f"{self.API_URL}auth/o/token/", data=data_token, headers=acc_headers) as r:
            if r.status != 200:
                raise BeatportError(f"Auth step 4 (Get Token) gagal: {await r.text()}")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.info(f"Beatport: Login Password berhasil untuk {email}")

    async def refresh(self):
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        headers = {'user-agent': USER_AGENT}
        
        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data, headers=headers) as r:
            if r.status != 200:
                LOGGER.error("Beatport: Gagal me-refresh token, mungkin perlu login ulang.")
                raise BeatportError("Gagal me-refresh token")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            self.refresh_token = resp_json['refresh_token']
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.debug("Beatport: Token berhasil di-refresh.")

    async def _get(self, endpoint: str, params: dict = None):
        """Fungsi pembantu GET request dengan Auto-Retry (Updated)."""
        await self._init_session()
        if not params:
            params = {}

        if self.expires and datetime.now() > self.expires:
            try:
                LOGGER.info(f"Token expired untuk {self.email}, mencoba refresh...")
                await self.refresh()
            except Exception as e:
                LOGGER.warning(f"Refresh token gagal: {e}. Mencoba Login Ulang Otomatis...")
                
                # [LOGIKA BARU] Coba Login Ulang Pakai Password Tersimpan
                if self.email and hasattr(self, 'password_cache') and self.password_cache:
                    try:
                        await self.login(self.email, self.password_cache)
                        LOGGER.info("Auto Re-Login Berhasil!")
                    except Exception as login_err:
                        raise BeatportError(f"Sesi habis dan Login Ulang gagal: {login_err}")
                else:
                    raise BeatportError(f"Token expired dan tidak ada password tersimpan: {e}")

        # [MODIFIKASI] Tambahkan logika Retry Loop
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(use_access_token=True)) as r:
                    
                    # 1. Sukses
                    if r.status == 200:
                        return await r.json()

                    # 2. Server Error / Gateway Timeout (502, 503, 504) -> Coba Lagi
                    if r.status in [500, 502, 503, 504]:
                        if attempt < max_retries - 1:
                            LOGGER.warning(f"Beatport API {r.status} (Percobaan {attempt+1}/{max_retries}). Mengulang dalam 2 detik...")
                            await asyncio.sleep(2)
                            continue
                        else:
                            raise ConnectionError(f"Beatport API Error {r.status}: {await r.text()}")

                    # 3. Client Error (4xx) -> Jangan Retry
                    if r.status == 401:
                        raise BeatportError("Token tidak valid atau kedaluwarsa.")
                    
                    if r.status == 403:
                        try:
                            detail = (await r.json()).get("detail", "")
                            if "Territory" in detail:
                                raise BeatportError("Region locked (Territory Restricted)")
                        except: pass
                        raise BeatportError(f"Akses ditolak (403): {await r.text()}")
                    
                    if r.status == 404:
                        raise BeatportError(f"Item tidak ditemukan (404)")
                    
                    # Error lainnya
                    raise ConnectionError(f"Beatport API Error {r.status}: {await r.text()}")

            except aiohttp.ClientConnectorError as e:
                # 4. Koneksi Putus (Proxy/Internet) -> Coba Lagi
                if attempt < max_retries - 1:
                    LOGGER.warning(f"Koneksi Beatport error: {e}. Mengulang...")
                    await asyncio.sleep(2)
                    continue
                raise e

    # --- Endpoint Katalog ---

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
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
