# [GANTI SELURUH FILE: bot/helpers/beatsource/api.py]

import aiohttp
import asyncio
import random
from datetime import timedelta, datetime
from urllib.parse import urlparse, parse_qs
from bot.logger import LOGGER

# --- Cek Library Proxy ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None
# -------------------------

# [FIX] Definisi User-Agent
# API_USER_AGENT: Untuk request ke API (Meniru aplikasi Orpheus agar sesuai Client ID)
# BROWSER_USER_AGENT: Untuk proses Login (Meniru Browser agar cookie sessionid valid)
API_USER_AGENT = "orpheusdl/beatsource-module"
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

# [PENTING] Alias ini ditambahkan agar handler.py tidak error saat import 'USER_AGENT'
USER_AGENT = API_USER_AGENT 

class BeatsourceError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatsourceError, self).__init__(message)

class BeatsourceAPI:
    def __init__(self):
        self.API_URL = "https://api.beatsource.com/v4/"
        # Client ID dari referensi (Orpheus/BeatportDL Go)
        self.client_id = "ryZ8LuyQVPqbK2mBX2Hwt4qSMtnWuTYSqBPO92yQ"

        self.access_token = None
        self.refresh_token = None
        self.expires = None
        
        self.email = None
        self.password_cache = None
        self.proxy = None
        self.session = None 

    async def _init_session(self):
        """
        Membuat sesi aiohttp dengan dukungan Proxy (Auto-fix socks5h).
        """
        if self.session is None or self.session.closed:
            connector = None
            if self.proxy and ProxyConnector:
                try:
                    proxy_url = self.proxy
                    use_rdns = False
                    if proxy_url.startswith("socks5h://"):
                        proxy_url = proxy_url.replace("socks5h://", "socks5://")
                        use_rdns = True
                    
                    connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                except Exception as e:
                    LOGGER.error(f"BeatsourceAPI: Gagal Proxy: {e}")

            # Gunakan cookie jar unsafe=True untuk menyimpan sessionid
            self.session = aiohttp.ClientSession(
                headers={'user-agent': API_USER_AGENT},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                connector=connector
            )

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    def _get_headers(self, use_access_token: bool = False):
        headers = {'user-agent': API_USER_AGENT}
        if use_access_token and self.access_token:
            headers['authorization'] = f'Bearer {self.access_token}'
        return headers

    async def load_session(self, token_data: dict):
        await self._init_session()
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')
        self.email = token_data.get('email')
        self.expires = datetime.now() - timedelta(seconds=10) # Force refresh check

    async def login(self, email: str, password: str):
        """
        Login Flow yang diperbaiki meniru referensi interface.py
        """
        self.email = email
        self.password_cache = password
        await self._init_session()
        
        # Gunakan Browser User-Agent hanya untuk Login Step
        login_headers = {"User-Agent": BROWSER_USER_AGENT}
        
        try:
            # 1. Login POST (Get sessionid cookie)
            login_url = f"{self.API_URL}auth/login/"
            login_payload = {"username": email, "password": password}
            
            async with self.session.post(login_url, json=login_payload, headers=login_headers) as r_login:
                if r_login.status != 200:
                    try:
                        err = await r_login.json()
                        if "non_field_errors" in err:
                            raise BeatsourceError(f"Login gagal: {err['non_field_errors'][0]}")
                    except: pass
                    raise BeatsourceError(f"Login step 1 gagal: {r_login.status}")

            # Validasi Session ID cookie (Sesuai referensi)
            cookies = self.session.cookie_jar.filter_cookies(self.API_URL)
            if 'sessionid' not in cookies:
                raise BeatsourceError("Login gagal: Cookie sessionid tidak ditemukan.")

            # 2. Authorize GET (Get Code)
            auth_url = f"{self.API_URL}auth/o/authorize/"
            auth_params = {
                "client_id": self.client_id,
                "response_type": "code",
            }
            # allow_redirects=False penting untuk tangkap header Location
            async with self.session.get(auth_url, params=auth_params, headers=login_headers, allow_redirects=False) as r_auth:
                if r_auth.status != 302:
                    raise BeatsourceError(f"Auth step 2 gagal (No redirect): {r_auth.status}")
                
                location = r_auth.headers.get('Location')
                if not location:
                    raise BeatsourceError("Auth step 2 gagal: Header Location hilang.")
                
                try:
                    parsed = urlparse(location)
                    code = parse_qs(parsed.query).get('code', [None])[0]
                except: code = None
                
                if not code:
                    raise BeatsourceError("Gagal mengambil auth code.")

            # 3. Token POST (Get Tokens)
            token_url = f"{self.API_URL}auth/o/token/"
            token_payload = {
                "client_id": self.client_id,
                "code": code,
                "grant_type": "authorization_code",
            }
            # Content-Type form-urlencoded otomatis handled by 'data=' param aiohttp
            # Gunakan Browser UA disini juga sesuai referensi
            async with self.session.post(token_url, data=token_payload, headers=login_headers) as r_token:
                if r_token.status != 200:
                    raise BeatsourceError(f"Token exchange gagal: {await r_token.text()}")
                
                js = await r_token.json()
                self.access_token = js['access_token']
                self.refresh_token = js['refresh_token']
                self.expires = datetime.now() + timedelta(seconds=js['expires_in'])
                LOGGER.info(f"Beatsource: Login berhasil untuk {email}")

        except Exception as e:
            await self.close_session()
            raise e

    async def refresh(self):
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        # Gunakan Browser UA untuk refresh (sesuai referensi)
        headers = {"User-Agent": BROWSER_USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"}
        
        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data, headers=headers) as r:
            if r.status != 200:
                raise BeatsourceError("Gagal refresh token.")
            
            js = await r.json()
            self.access_token = js['access_token']
            self.refresh_token = js.get('refresh_token', self.refresh_token)
            self.expires = datetime.now() + timedelta(seconds=js['expires_in'])

    async def _get(self, endpoint: str, params: dict = None):
        """Helper GET dengan Auto-Retry dan Delay."""
        await self._init_session()
        if not params: params = {}

        # Cek Expired
        if self.expires and datetime.now() > self.expires:
            try:
                await self.refresh()
            except:
                if self.email and self.password_cache:
                    await self.login(self.email, self.password_cache)
                else:
                    raise BeatsourceError("Sesi habis, gagal login ulang.")

        # Tambahkan Random Sleep untuk Human-Like behavior
        await asyncio.sleep(random.uniform(0.2, 0.5))

        for attempt in range(3):
            try:
                # Gunakan API User Agent (Orpheus) untuk request data
                async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(True)) as r:
                    
                    if r.status == 200:
                        return await r.json()

                    if r.status in [500, 502, 503, 504]:
                        await asyncio.sleep(2)
                        continue
                    
                    if r.status == 401:
                        raise BeatsourceError("Unauthorized (401)")
                    
                    if r.status == 403:
                        try:
                            d = await r.json()
                            if "Territory" in str(d): raise BeatsourceError("Region Locked")
                        except: pass
                        raise BeatsourceError(f"Forbidden (403): {await r.text()}")
                    
                    if r.status == 404:
                        raise BeatsourceError(f"Not Found (404): {endpoint}")
                    
                    raise ConnectionError(f"API Error {r.status}")
            except aiohttp.ClientConnectorError:
                await asyncio.sleep(2)
                continue
                
    # --- Endpoints ---
    async def get_account(self): return await self._get('auth/o/introspect')
    async def get_track(self, track_id: str): return await self._get(f'catalog/tracks/{track_id}')
    async def get_release(self, release_id: str): return await self._get(f'catalog/releases/{release_id}')
    
    async def get_release_tracks(self, release_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/releases/{release_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_playlist(self, playlist_id: str): return await self._get(f'catalog/playlists/{playlist_id}')
    async def get_playlist_tracks(self, playlist_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/playlists/{playlist_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_chart(self, chart_id: str): return await self._get(f'catalog/charts/{chart_id}')
    async def get_chart_tracks(self, chart_id: str, page: int = 1, per_page: int = 100):
        return await self._get(f'catalog/charts/{chart_id}/tracks', params={'page': page, 'per_page': per_page})

    async def get_track_download(self, track_id: str, quality: str):
        return await self._get(f'catalog/tracks/{track_id}/download', params={'quality': quality})
