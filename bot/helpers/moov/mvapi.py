# [GANTI FILE: bot/helpers/moov/mvapi.py]

import aiohttp
import asyncio
import uuid
from bot.logger import LOGGER

# --- Konektor Proxy ---
try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    LOGGER.warning("Modul 'aiohttp-socks' tidak ditemukan. Proxy SOCKS5 mungkin tidak jalan.")
    ProxyConnector = None
# ----------------------

class MoovAPI:
    def __init__(self, proxy=None):
        self.base_url = "https://mtg.now.com/moov/api"
        self.session = None
        self.proxy = proxy
        
        # CREDENTIAL STORAGE UNTUK AUTO RE-LOGIN
        self.email = None
        self.password = None
        
        # GENERATE RANDOM DEVICE ID (Agar tidak terdeteksi spam)
        self.device_id = str(uuid.uuid4())

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10.0.0; PIXEL 2XL Build/NOF26V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36/Moov',
            'Referer': 'https://moov.hk/',
            'Origin': 'https://moov.hk'
        }

    async def _get_session(self, force_new=False):
        if force_new and self.session and not self.session.closed:
            await self.session.close()
            self.session = None

        if not self.session or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            
            if self.proxy:
                if not ProxyConnector:
                    LOGGER.error("Proxy diset tapi aiohttp-socks tidak ada.")
                    self.session = aiohttp.ClientSession(timeout=timeout)
                else:
                    proxy_url = self.proxy
                    use_rdns = False 
                    if proxy_url.startswith("socks5h://"):
                        proxy_url = proxy_url.replace("socks5h://", "socks5://")
                        use_rdns = True
                    
                    LOGGER.info(f"MoovAPI: New Session via Proxy (RDNS={use_rdns})")
                    connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                    self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            else:
                self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def login(self, email, password):
        # Simpan kredensial untuk auto re-login nanti
        self.email = email
        self.password = password
        
        session = await self._get_session(force_new=True) # Reset session saat login baru
        
        data = {
            'deviceid': self.device_id,
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
                    LOGGER.info(f"Moov: Login Sukses ({email})")
                    return True
                
                # Cek respon error
                text = await resp.text()
                LOGGER.error(f"Moov Login Failed: {text[:100]}...")
                return False
        except Exception as e:
            LOGGER.error(f"Moov Login Error: {e}")
            return False

    async def _ensure_active_session(self):
        """Helper untuk memastikan session aktif, atau login ulang jika perlu"""
        if not self.session or self.session.closed:
            if self.email and self.password:
                LOGGER.info("Moov: Session mati, mencoba Auto Re-login...")
                await self.login(self.email, self.password)
            else:
                await self._get_session()

    async def get_album_meta(self, album_id):
        await self._ensure_active_session()
        session = await self._get_session()
        params = {
            'profileId': album_id,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': 'PAB',
            'checksum': ''
        }
        try:
            async with session.get(f"{self.base_url}/profile/getProfile", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject')
        except Exception as e:
            LOGGER.error(f"Moov API Error (Album {album_id}): {e}")
            return None

    async def get_playlist_meta(self, pid):
        await self._ensure_active_session()
        session = await self._get_session()
        
        attempts = []
        if str(pid).startswith("PC"):
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"}, 
                {"endpoint": "profile/getProfile", "refType": "PC"}, 
                {"endpoint": "profile/getProfile", "refType": "PAB"}, 
                {"endpoint": "profile/getProfile", "refType": "CAT"}, 
                {"endpoint": "playlist/getProfile", "refType": "CAT"} 
            ]
        elif str(pid).startswith("PP"):
             attempts = [
                {"endpoint": "profile/getProfile", "refType": "PP"},
                {"endpoint": "profile/getProfile", "refType": "PAB"},
                {"endpoint": "profile/getProfile", "refType": "CAT"}
             ]
        else:
             attempts = [
                {"endpoint": "playlist/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "CAT"},
                {"endpoint": "profile/getProfile", "refType": "PAB"}
            ]

        for config in attempts:
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
                        try:
                            data = await resp.json()
                        except: continue
                        data_obj = data.get('dataObject')
                        if data_obj and (data_obj.get('modules') or data_obj.get('tracks') or data_obj.get('products')):
                            return data_obj
            except: continue
        return None

    async def get_product_meta(self, product_id):
        await self._ensure_active_session()
        session = await self._get_session()
        params = {'productId': product_id, 'deviceType': 'phones3'}
        try:
            async with session.get(f"{self.base_url}/product/getProduct", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject')
        except: return None

    async def get_track_file_meta(self, track_id, quality='LL', album_id=None):
        # Retry loop: 0 = Normal attempt, 1 = Retry after Login
        for attempt_no in range(2): 
            await self._ensure_active_session()
            session = await self._get_session()
            
            stream_headers = {
                'User-Agent': 'okhttp/4.8.0',
                'Referer': 'https://moov.hk/'
            }
            
            attempts_config = []
            if album_id:
                attempts_config.append({'cat': 'product', 'refid': album_id, 'refType': 'PAB'})
                attempts_config.append({'cat': 'song', 'refid': album_id, 'refType': 'PAB'})
                attempts_config.append({'cat': 'album', 'refid': album_id, 'refType': 'PAB'})
            
            attempts_config.append({'cat': 'product', 'refid': '', 'refType': ''})
            attempts_config.append({'cat': 'song', 'refid': '', 'refType': ''})
            attempts_config.append({'cat': 'video', 'refid': '', 'refType': ''})

            for conf in attempts_config:
                params = {
                    'clientver': '3.0.7',
                    'action': 'stream',
                    'streamtype': 'stdhls',
                    'preview': 'F',
                    'cat': conf['cat'], 
                    'pid': track_id,
                    'isUpSample': 'false',
                    'osver': '10.0.0',
                    'refid': conf['refid'],      
                    'quality': quality,
                    'devicetype': 'Android',
                    'connect': 'WiFi',
                    'refType': conf['refType'], 
                    'deviceid': self.device_id,
                    'application': 'moovnext',
                    'isStudioMaster': 'true'
                }
                
                try:
                    async with session.get(f"{self.base_url}/content/checkout", headers=stream_headers, params=params) as resp:
                        if resp.status != 200: 
                            continue
                        
                        data = await resp.json()
                        data_obj = data.get('result', {}).get('dataObject')
                        
                        if data_obj and data_obj.get('playUrl') and data_obj.get('contentKey'):
                            return data_obj
                        
                        # Jika respon ada tapi playUrl kosong, mungkin session mati
                        # Kita biarkan loop berlanjut, jika semua conf gagal, kita masuk blok 'if attempt_no == 0'
                        
                except Exception:
                    continue
            
            # Jika sampai sini dan attempt_no == 0 (percobaan pertama gagal)
            # Maka lakukan Re-login dan ulang loop
            if attempt_no == 0:
                if self.email and self.password:
                    LOGGER.warning(f"Moov Checkout Gagal ({track_id}). Mencoba Re-login otomatis...")
                    login_success = await self.login(self.email, self.password)
                    if login_success:
                        # Login sukses, lanjut ke attempt_no = 1 (Retry)
                        continue
                    else:
                        # Login gagal, stop
                        break
                else:
                    break

        return {}

    async def get_lyrics(self, track_id):
        await self._ensure_active_session()
        session = await self._get_session()
        params = {'pid': track_id}
        try:
            async with session.get(f"{self.base_url}/lyric/getLyric", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject', {}).get('lyric')
        except: return None

    async def close(self):
        if self.session:
            await self.session.close()
