# [GANTI FILE: bot/helpers/moov/mvapi.py]

import aiohttp
import asyncio
from bot.logger import LOGGER

# --- Konektor Proxy ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.critical("Modul 'aiohttp-socks' tidak ditemukan. Silakan install dengan 'pip install aiohttp-socks'")
    ProxyConnector = None
# ----------------------

class MoovAPI:
    def __init__(self, proxy=None):
        self.base_url = "https://mtg.now.com/moov/api"
        self.session = None
        self.token = None
        self.user_id = None
        self.proxy = proxy
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10.0.0; PIXEL 2XL Build/NOF26V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36/Moov'
        }

    async def _get_session(self):
        if not self.session or self.session.closed:
            if self.proxy:
                if not ProxyConnector:
                    raise ImportError("Anda menggunakan Proxy SOCKS5 tapi 'aiohttp-socks' belum diinstal.")
                
                proxy_url = self.proxy
                use_rdns = False 

                if proxy_url.startswith("socks5h://"):
                    proxy_url = proxy_url.replace("socks5h://", "socks5://")
                    use_rdns = True
                
                LOGGER.info(f"MoovAPI: Menggunakan ProxyConnector (RDNS={use_rdns})")
                connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                self.session = aiohttp.ClientSession(connector=connector)
            else:
                self.session = aiohttp.ClientSession()
        return self.session

    async def login(self, email, password):
        session = await self._get_session()
        
        data = {
            'deviceid': 'fgq7hzlFQE-Gsf7sj9RiC5',
            'devicetype': 'Android',
            'clientver': '3.0.7',
            'brand': 'Android',
            'model': 'PIXEL+2XL',
            'os': 'Android',
            'osver': '10.0.0',
            'devicename': 'Google+PIXEL+2XL',
            'connect': 'WiFi',
            'lang': 'en_US',
            'loginid': email,
            'notifyid': '',
            'password': password,
            'autologin': 'true'
        }
        
        try:
            async with session.post(
                f"{self.base_url}/user/loginstatuscheck", 
                headers=self.headers, 
                data=data
            ) as resp:
                if resp.headers.get('Content-Type') == "application/xml;charset=UTF-8":
                    self.email = email
                    return True
                text = await resp.text()
                LOGGER.error(f"Moov Login Failed Response: {text}")
                return False
        except Exception as e:
            LOGGER.error(f"Moov Login Error: {e}")
            return False

    async def get_album_meta(self, album_id):
        session = await self._get_session()
        params = {
            'profileId': album_id,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': 'PAB',
            'checksum': ''
        }
        async with session.get(f"{self.base_url}/profile/getProfile", headers=self.headers, params=params) as resp:
            data = await resp.json()
            return data.get('dataObject')

    # --- PERBAIKAN UTAMA DI SINI ---
    async def get_playlist_meta(self, pid):
        session = await self._get_session()
        
        # Logika Deteksi:
        # ID yang berawalan "PC" (Chart) atau "PP" (Program Playlist) biasanya ada di endpoint Profile
        # ID angka/UUID biasanya Playlist User ada di endpoint Playlist
        is_profile_type = str(pid).startswith("PC") or str(pid).startswith("PP")
        
        # Percobaan 1: Tentukan endpoint berdasarkan tebakan awal
        if is_profile_type:
            endpoint = "profile/getProfile"
            ref_type = "PAB"
        else:
            endpoint = "playlist/getProfile"
            ref_type = "CAT"

        params = {
            'profileId': pid,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': ref_type,
            'checksum': ''
        }
        
        try:
            async with session.get(f"{self.base_url}/{endpoint}", headers=self.headers, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('dataObject')
                elif resp.status == 404:
                    # FALLBACK: Jika tebakan salah (404), coba endpoint sebaliknya
                    LOGGER.warning(f"Moov: {endpoint} gagal (404), mencoba endpoint alternatif...")
                    return await self._get_playlist_fallback(pid, is_profile_type)
        except Exception as e:
            LOGGER.error(f"Moov API Error (Percobaan 1): {e}")
            raise e
            
        return None

    async def _get_playlist_fallback(self, pid, prev_was_profile):
        session = await self._get_session()
        
        # Tukar endpoint
        if prev_was_profile:
            endpoint = "playlist/getProfile"
            ref_type = "CAT"
        else:
            endpoint = "profile/getProfile"
            ref_type = "PAB"
            
        params = {
            'profileId': pid,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': ref_type,
            'checksum': ''
        }
        
        async with session.get(f"{self.base_url}/{endpoint}", headers=self.headers, params=params) as resp:
            data = await resp.json()
            return data.get('dataObject')
    # -------------------------------

    async def get_product_meta(self, product_id):
        session = await self._get_session()
        params = {
            'productId': product_id,
            'deviceType': 'phones3'
        }
        async with session.get(f"{self.base_url}/product/getProduct", headers=self.headers, params=params) as resp:
            data = await resp.json()
            return data.get('dataObject')

    async def get_track_file_meta(self, track_id, quality='LL'):
        session = await self._get_session()
        stream_headers = {'User-Agent': 'okhttp/4.8.0'}
        
        params = {
            'clientver': '3.0.7',
            'action': 'stream',
            'streamtype': 'stdhls',
            'preview': 'F',
            'cat': 'playlist',
            'pid': track_id,
            'isUpSample': 'false',
            'osver': '10.0.0',
            'refid': '',
            'quality': quality,
            'devicetype': 'Android',
            'connect': 'WiFi',
            'reftype': '',
            'deviceid': 'fgq7hzlFQE-Gsf7sj9RiC5',
            'application': 'moovnext',
            'isStudioMaster': 'true'
        }
        
        async with session.get(f"{self.base_url}/content/checkout", headers=stream_headers, params=params) as resp:
            data = await resp.json()
            return data.get('result', {}).get('dataObject')

    async def get_lyrics(self, track_id):
        session = await self._get_session()
        params = {'pid': track_id}
        async with session.get(f"{self.base_url}/lyric/getLyric", headers=self.headers, params=params) as resp:
            data = await resp.json()
            return data.get('dataObject', {}).get('lyric')

    async def close(self):
        if self.session:
            await self.session.close()
