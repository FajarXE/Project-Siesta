import aiohttp
import hashlib
from bot.logger import LOGGER

class MoovAPI:
    def __init__(self, proxy=None):
        self.base_url = "https://mtg.now.com/moov/api"
        self.session = None
        self.token = None
        self.user_id = None
        self.proxy = proxy  # Proxy wajib untuk Moov (HK)
        
        # Headers statis meniru Android App
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10.0.0; PIXEL 2XL Build/NOF26V; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/74.0.3729.136 Mobile Safari/537.36/Moov'
        }

    async def _get_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def login(self, email, password):
        """
        Login ke Moov.
        """
        session = await self._get_session()
        
        # Payload login statis sesuai source code client.py
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
                data=data,
                proxy=self.proxy
            ) as resp:
                # Moov mengembalikan XML di header jika sukses
                if resp.headers.get('Content-Type') == "application/xml;charset=UTF-8":
                    self.email = email
                    return True
                return False
        except Exception as e:
            LOGGER.error(f"Moov Login Error: {e}")
            return False

    async def get_album_meta(self, album_id):
        """Ambil metadata album"""
        session = await self._get_session()
        params = {
            'profileId': album_id,
            'features': '24bit',
            'deviceType': 'phones3',
            'refType': 'PAB',
            'checksum': ''
        }
        async with session.get(f"{self.base_url}/profile/getProfile", headers=self.headers, params=params, proxy=self.proxy) as resp:
            data = await resp.json()
            return data.get('dataObject')

    async def get_track_file_meta(self, track_id, quality='LL'):
        """
        Mendapatkan info file stream (m3u8 & contentKey). 
        Quality: 'LL' (Lossless/16bit) atau 'HR' (Hi-Res/24bit)
        """
        session = await self._get_session()
        # Header khusus untuk request stream
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
        
        async with session.get(f"{self.base_url}/content/checkout", headers=stream_headers, params=params, proxy=self.proxy) as resp:
            data = await resp.json()
            return data.get('result', {}).get('dataObject')

    async def get_lyrics(self, track_id):
        """Ambil lirik"""
        session = await self._get_session()
        params = {'pid': track_id}
        async with session.get(f"{self.base_url}/lyric/getLyric", headers=self.headers, params=params, proxy=self.proxy) as resp:
            data = await resp.json()
            return data.get('dataObject', {}).get('lyric')

    async def close(self):
        if self.session:
            await self.session.close()
