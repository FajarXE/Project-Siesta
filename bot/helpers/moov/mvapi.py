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

    # --- PERBAIKAN LOGIKA: MENAMBAHKAN refType PP dan PC ---
    async def get_playlist_meta(self, pid):
        session = await self._get_session()
        
        attempts = []
        
        # Deteksi tipe ID
        if str(pid).startswith("PC"):
             # PC = Program Chart. Coba variasi Program (PP/PC) sebelum Fallback ke CAT
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"},  # Prioritas 1: Program Playlist
                {"endpoint": "profile/getProfile", "refType": "PC"},  # Prioritas 2: Program Chart (Direct)
                {"endpoint": "profile/getProfile", "refType": "PAB"}, # Prioritas 3: Profile Album
                {"endpoint": "profile/getProfile", "refType": "CAT"}, # Prioritas 4: Category (sering kosong)
                {"endpoint": "playlist/getProfile", "refType": "CAT"} # Fallback
            ]
        elif str(pid).startswith("PP"):
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"},
                {"endpoint": "profile/getProfile", "refType": "PAB"},
                {"endpoint": "profile/getProfile", "refType": "CAT"}
             ]
        else:
             # Playlist User Biasa (Angka/UUID)
             attempts = [
                {"endpoint": "playlist/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "PAB"}
            ]

        last_error = None

        for i, config in enumerate(attempts):
            endpoint = config['endpoint']
            ref_type = config['refType']
            
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
                        data_obj = data.get('dataObject')
                        
                        if data_obj:
                            # --- VALIDASI ISI ---
                            has_content = False
                            
                            # Cek modules
                            if data_obj.get('modules') and len(data_obj.get('modules')) > 0:
                                has_content = True
                            
                            # Cek tracks/products
                            elif data_obj.get('tracks') or data_obj.get('products'): 
                                has_content = True
                            
                            # Cek data tersembunyi (khusus chart)
                            elif data_obj.get('data') and (data_obj['data'].get('tracks') or data_obj['data'].get('products')):
                                has_content = True
                            
                            if has_content:
                                LOGGER.info(f"Moov: Metadata VALID ditemukan menggunakan {endpoint} (refType={ref_type})")
                                return data_obj
                            else:
                                LOGGER.warning(f"Moov: Metadata ditemukan di {endpoint} (refType={ref_type}) tapi KOSONG. Mencoba opsi lain...")
                        else:
                            # Response 200 tapi dataObject null
                            pass 

            except Exception as e:
                last_error = e
                continue
        
        if last_error:
            LOGGER.error(f"Moov: Gagal mengambil metadata setelah {len(attempts)} percobaan. Error terakhir: {last_error}")
        return None

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
