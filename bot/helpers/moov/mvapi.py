# [GANTI FILE: bot/helpers/moov/mvapi.py]

import aiohttp
import asyncio
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
        self.token = None
        self.user_id = None
        self.proxy = proxy
        
        # FIX: Tambahkan Referer agar tidak dianggap bot
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10.0.0; PIXEL 2XL Build/NOF26V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36/Moov',
            'Referer': 'https://moov.hk/',
            'Origin': 'https://moov.hk'
        }

    async def _get_session(self):
        if not self.session or self.session.closed:
            # --- KONFIGURASI TIMEOUT YANG LEBIH SABAR ---
            timeout = aiohttp.ClientTimeout(total=120, connect=60)
            
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
                    
                    LOGGER.info(f"MoovAPI: Menggunakan ProxyConnector (RDNS={use_rdns}, Timeout=60s)")
                    connector = ProxyConnector.from_url(proxy_url, rdns=use_rdns)
                    self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            else:
                self.session = aiohttp.ClientSession(timeout=timeout)
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
        try:
            async with session.get(f"{self.base_url}/profile/getProfile", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject')
        except Exception as e:
            LOGGER.error(f"Moov API Error (Album {album_id}): {e}")
            return None

    async def get_playlist_meta(self, pid):
        session = await self._get_session()
        
        attempts = []
        
        # Logika brute-force endpoint playlist yang lebih cerdas
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
                        if data_obj:
                            # Cek validitas isi
                            has_content = False
                            if data_obj.get('modules') and len(data_obj.get('modules')) > 0: has_content = True
                            elif data_obj.get('tracks') or data_obj.get('products'): has_content = True
                            elif data_obj.get('data') and (data_obj['data'].get('tracks') or data_obj['data'].get('products')): has_content = True
                            
                            if has_content:
                                LOGGER.info(f"Moov: Metadata VALID ditemukan menggunakan {endpoint} (refType={ref_type})")
                                return data_obj
            except:
                continue
        
        return None

    async def get_product_meta(self, product_id):
        session = await self._get_session()
        params = {
            'productId': product_id,
            'deviceType': 'phones3'
        }
        try:
            async with session.get(f"{self.base_url}/product/getProduct", headers=self.headers, params=params) as resp:
                if resp.status != 200:
                    return None
                try:
                    data = await resp.json()
                    return data.get('dataObject')
                except Exception:
                    return None
        except Exception as e:
            LOGGER.error(f"Moov getProduct Exception ({product_id}): {e}")
            return None

    async def get_track_file_meta(self, track_id, quality='LL', album_id=None):
        session = await self._get_session()
        stream_headers = {
            'User-Agent': 'okhttp/4.8.0', # User-Agent aplikasi Android asli
            'Referer': 'https://moov.hk/'
        }
        
        # --- PERBAIKAN LOGIKA CHECKOUT ---
        # Kita membuat daftar percobaan (attempts) yang spesifik.
        # Masalah sebelumnya: 'product' dikirim TANPA refid, padahal butuh refid album.
        
        attempts = []

        # PRIORITAS 1: Jika ada Album ID, gunakan konteks album.
        if album_id:
            # Paling sering berhasil: Product checkout dengan referensi Album
            attempts.append({'cat': 'product', 'refid': album_id, 'refType': 'PAB'})
            # Kadang endpoint butuh 'song'
            attempts.append({'cat': 'song', 'refid': album_id, 'refType': 'PAB'})
            # Cara lama (album checkout)
            attempts.append({'cat': 'album', 'refid': album_id, 'refType': 'PAB'})

        # PRIORITAS 2: Coba tanpa konteks (Standalone) atau jika Playlist
        attempts.append({'cat': 'product', 'refid': '', 'refType': ''})
        attempts.append({'cat': 'song', 'refid': '', 'refType': ''})
        
        # PRIORITAS 3: Coba sebagai Video (kadang audio dideteksi sebagai MV)
        attempts.append({'cat': 'video', 'refid': '', 'refType': ''})

        for attempt in attempts:
            params = {
                'clientver': '3.0.7',
                'action': 'stream',
                'streamtype': 'stdhls',
                'preview': 'F',
                'cat': attempt['cat'], 
                'pid': track_id,
                'isUpSample': 'false',
                'osver': '10.0.0',
                'refid': attempt['refid'],      # Album ID (PENTING)
                'quality': quality,
                'devicetype': 'Android',
                'connect': 'WiFi',
                'refType': attempt['refType'],  # 'PAB' (CamelCase PENTING)
                'deviceid': 'fgq7hzlFQE-Gsf7sj9RiC5',
                'application': 'moovnext',
                'isStudioMaster': 'true'
            }
            
            try:
                # LOGGER.info(f"Mencoba checkout: cat={attempt['cat']}, refid={attempt['refid']}") # Debug
                async with session.get(f"{self.base_url}/content/checkout", headers=stream_headers, params=params) as resp:
                    if resp.status != 200: 
                        continue
                    
                    data = await resp.json()
                    data_obj = data.get('result', {}).get('dataObject')
                    
                    # Validasi ketat: Harus ada URL dan Key
                    if data_obj and data_obj.get('playUrl') and data_obj.get('contentKey'):
                        LOGGER.info(f"Moov Checkout Sukses: cat={attempt['cat']} (Q:{quality})")
                        return data_obj
                    
            except Exception as e:
                continue

        # Jika semua gagal
        return {}

    async def get_lyrics(self, track_id):
        session = await self._get_session()
        params = {'pid': track_id}
        try:
            async with session.get(f"{self.base_url}/lyric/getLyric", headers=self.headers, params=params) as resp:
                if resp.status != 200: return None
                data = await resp.json()
                return data.get('dataObject', {}).get('lyric')
        except:
            return None

    async def close(self):
        if self.session:
            await self.session.close()
