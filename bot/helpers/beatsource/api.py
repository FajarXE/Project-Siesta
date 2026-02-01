# [GANTI SELURUH FILE: bot/helpers/beatsource/api.py]

import aiohttp
import asyncio
from datetime import timedelta, datetime
from urllib.parse import urlparse, parse_qs
from bot.logger import LOGGER

# --- TAMBAHAN: Import ProxyConnector ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp_socks' tidak ditemukan. Proxy SOCKS/SOCKS5H tidak akan berjalan.")
    ProxyConnector = None
# ---------------------------------------

# --- KONSTANTA ANTI-BAN ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class BeatsourceError(Exception):
    def __init__(self, message):
        self.message = message
        super(BeatsourceError, self).__init__(message)

class BeatsourceAPI:
    def __init__(self):
        self.API_URL = "https://api.beatsource.com/v4/"
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
        Membuat sesi aiohttp dengan header browser, cookie jar, dan PROXY.
        CookieJar(unsafe=True) PENTING untuk login Beatsource agar cookie sessionid tersimpan.
        """
        if self.session is None or self.session.closed:
            connector = None
            
            # --- LOGIKA KONEKTOR PROXY (Auto-fix socks5h) ---
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
                        LOGGER.debug(f"BeatsourceAPI: Menggunakan Proxy untuk {self.email} (RDNS: {use_rdns})")
                    except Exception as e:
                        LOGGER.error(f"BeatsourceAPI: Gagal menginisialisasi Proxy Connector: {e}")
                else:
                    LOGGER.error("BeatsourceAPI: Proxy diset tapi 'aiohttp_socks' belum diinstall.")
            # ------------------------------------------------

            self.session = aiohttp.ClientSession(
                headers={'user-agent': USER_AGENT},
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                connector=connector
            )

    async def close_session(self):
        """Menutup sesi aiohttp dengan aman."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    def _get_headers(self, use_access_token: bool = False):
        """Mendapatkan header standar dengan User-Agent yang konsisten."""
        headers = {'user-agent': USER_AGENT}
        if use_access_token and self.access_token:
            headers['authorization'] = f'Bearer {self.access_token}'
        return headers

    async def load_session(self, token_data: dict):
        """Memuat sesi dari database."""
        await self._init_session()
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')
        self.email = token_data.get('email')
        
        # Paksa refresh token saat request pertama kali untuk validasi
        self.expires = datetime.now() - timedelta(seconds=10)
        
        LOGGER.debug(f"BeatsourceAPI: Sesi dimuat untuk {self.email} (Pending Refresh)")

    async def login(self, email: str, password: str):
        """Melakukan login OAuth 3 langkah penuh."""
        self.email = email
        self.password_cache = password
        await self._init_session()
        
        # Pastikan header login juga menggunakan User-Agent browser
        login_headers = {"User-Agent": USER_AGENT}
        
        try:
            # --- Langkah 1: POST Login (Mendapatkan cookie sessionid) ---
            login_url = f"{self.API_URL}auth/login/"
            login_payload = {"username": email, "password": password}
            
            async with self.session.post(login_url, json=login_payload, headers=login_headers) as r_login:
                if r_login.status != 200:
                    try:
                        resp_json = await r_login.json()
                        if "non_field_errors" in resp_json:
                            raise BeatsourceError(f"Login gagal: {resp_json['non_field_errors'][0]}")
                    except Exception:
                        pass 
                    raise BeatsourceError(f"Login Langkah 1 gagal (Status {r_login.status})")

            # --- Langkah 2: GET Authorize (Redirect untuk mendapatkan Code) ---
            auth_url = f"{self.API_URL}auth/o/authorize/"
            auth_params = {
                "client_id": self.client_id,
                "response_type": "code",
            }
            
            # allow_redirects=False agar kita bisa menangkap header Location
            async with self.session.get(auth_url, params=auth_params, headers=login_headers, allow_redirects=False) as r_auth:
                if r_auth.status != 302: 
                    raise BeatsourceError(f"Otorisasi Langkah 2 gagal (Status {r_auth.status}).")

                redirect_location = r_auth.headers.get('Location')
                if not redirect_location:
                    raise BeatsourceError("Otorisasi Langkah 2 tidak mengembalikan header Lokasi.")
                
                try:
                    parsed_url = urlparse(redirect_location)
                    query_params = parse_qs(parsed_url.query)
                    code = query_params.get('code', [None])[0]
                except Exception as e:
                    raise BeatsourceError(f"Gagal mem-parse code otorisasi: {e}")
                
                if not code:
                    raise BeatsourceError(f"Tidak dapat mengekstrak 'code' otorisasi.")

            # --- Langkah 3: POST Token (Tukar Code dengan Token) ---
            token_url = f"{self.API_URL}auth/o/token/"
            token_payload = {
                "client_id": self.client_id,
                "code": code,
                "grant_type": "authorization_code",
            }
            
            async with self.session.post(token_url, data=token_payload, headers=login_headers) as r_token:
                if r_token.status != 200:
                    raise BeatsourceError(f"Penukaran Token Langkah 3 gagal (Status {r_token.status})")
                
                resp_json = await r_token.json()
                self.access_token = resp_json['access_token']
                self.refresh_token = resp_json['refresh_token']
                self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
                LOGGER.info(f"Beatsource: Login Password berhasil untuk {email}")

        except Exception as e:
            await self.close_session()
            raise e

    async def refresh(self):
        """Me-refresh access token menggunakan refresh token."""
        await self._init_session()
        data = {
            'client_id': self.client_id,
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token',
        }
        
        # Header user-agent tetap konsisten
        headers = self._get_headers(use_access_token=False)

        async with self.session.post(f'{self.API_URL}auth/o/token/', data=data, headers=headers) as r:
            if r.status != 200:
                LOGGER.error("Beatsource: Gagal me-refresh token, perlu login ulang.")
                raise BeatsourceError("Gagal me-refresh token")
            
            resp_json = await r.json()
            self.access_token = resp_json['access_token']
            # Kadang refresh token juga diperbarui (rotating refresh tokens)
            self.refresh_token = resp_json.get('refresh_token', self.refresh_token)
            self.expires = datetime.now() + timedelta(seconds=resp_json['expires_in'])
            LOGGER.debug("Beatsource: Token berhasil di-refresh.")

    async def _get(self, endpoint: str, params: dict = None):
        """Fungsi pembantu GET request dengan Auto-Retry untuk Error 5xx."""
        await self._init_session()
        if not params:
            params = {}

        # Cek apakah token sudah kedaluwarsa
        if self.expires and datetime.now() > self.expires:
            try:
                LOGGER.info(f"Token expired untuk {self.email}, mencoba refresh...")
                await self.refresh()
            except Exception as e:
                LOGGER.warning(f"Refresh token gagal: {e}. Mencoba Login Ulang Otomatis...")
                
                # [BARU] Logika Auto Re-Login
                if self.email and hasattr(self, 'password_cache') and self.password_cache:
                    try:
                        # Login ulang menggunakan password yang disimpan
                        await self.login(self.email, self.password_cache)
                        LOGGER.info("Auto Re-Login Berhasil!")
                    except Exception as login_err:
                        raise BeatsourceError(f"Sesi habis dan Login Ulang gagal: {login_err}")
                else:
                    raise BeatsourceError(f"Token expired dan tidak ada password tersimpan: {e}")

        # [MODIFIKASI] RETRY LOGIC (Mencoba maks 3 kali)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with self.session.get(f'{self.API_URL}{endpoint}', params=params, headers=self._get_headers(use_access_token=True)) as r:
                    
                    # Jika sukses (200), langsung return
                    if r.status == 200:
                        return await r.json()

                    # [BARU] Jika Error Server (502/503/504), tunggu dan coba lagi
                    if r.status in [500, 502, 503, 504]:
                        if attempt < max_retries - 1:
                            LOGGER.warning(f"Beatsource API {r.status} (Percobaan {attempt+1}/{max_retries}). Mengulang dalam 2 detik...")
                            await asyncio.sleep(2)
                            continue
                        else:
                            # Jika sudah 3x gagal, baru raise error
                            raise ConnectionError(f"Beatsource API Error {r.status}: {await r.text()}")

                    # Error Klien (4xx) tidak perlu retry (salah password/region/dll)
                    if r.status == 401:
                        raise BeatsourceError("Token tidak valid atau kedaluwarsa (401).")
                    
                    if r.status == 403:
                        try:
                            detail = (await r.json()).get("detail", "")
                            if "Territory" in detail:
                                raise BeatsourceError("Gagal: Region Locked (Territory Restricted)")
                        except: pass
                        raise BeatsourceError(f"Akses ditolak (403): {await r.text()}")
                    
                    if r.status == 404:
                        raise BeatsourceError(f"Item tidak ditemukan (404)")
                    
                    # Error lainnya yang tidak tertangani
                    raise ConnectionError(f"Beatsource API Error {r.status}: {await r.text()}")

            except aiohttp.ClientConnectorError as e:
                # [BARU] Retry juga jika koneksi internet/proxy putus total
                if attempt < max_retries - 1:
                    LOGGER.warning(f"Koneksi error: {e}. Mengulang...")
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
