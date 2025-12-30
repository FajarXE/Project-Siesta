import aiohttp
import json

class JioSaavnAPI:
    def __init__(self):
        self.base_url = "https://www.jiosaavn.com/api.php"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def get_song_details(self, session: aiohttp.ClientSession, token: str):
        params = {
            '__call': 'webapi.get',
            'token': token,
            'type': 'song',
            '_format': 'json',
            'ctx': 'web6dot0'
        }
        async with session.get(self.base_url, params=params, headers=self.headers) as resp:
            try:
                text = await resp.text()
                clean_json = json.loads(text.split('-->')[-1] if '-->' in text else text)
            except:
                return None
            
            if "songs" in clean_json and clean_json["songs"]: 
                 return clean_json["songs"][0]
            if isinstance(clean_json, dict) and len(clean_json) > 0:
                key = list(clean_json.keys())[0]
                if isinstance(clean_json[key], dict):
                    return clean_json[key]
            return None

    async def get_album_details(self, session: aiohttp.ClientSession, token: str):
        params = {
            '__call': 'webapi.get',
            'token': token,
            'type': 'album',
            '_format': 'json',
            'ctx': 'web6dot0'
        }
        async with session.get(self.base_url, params=params, headers=self.headers) as resp:
            try:
                text = await resp.text()
                clean_json = json.loads(text.split('-->')[-1] if '-->' in text else text)
                return clean_json
            except:
                return None

    async def get_auth_url(self, session: aiohttp.ClientSession, encrypted_url: str, preview_url: str = None):
        """
        Mencoba mendapatkan URL via API. Jika gagal, mencoba convert manual dari preview_url.
        """
        # 1. Coba Cara Resmi (API)
        params = {
            '__call': 'song.generateAuthToken',
            'url': encrypted_url,
            'bitrate': '320',
            'api_version': '4',
            '_format': 'json',
            'ctx': 'web6dot0',
            '_marker': '0',
        }
        try:
            async with session.get(self.base_url, params=params, headers=self.headers) as resp:
                data = await resp.json()
                auth_url = data.get("auth_url")
                if auth_url:
                    if "preview" in auth_url:
                        auth_url = auth_url.replace("preview", "aac")
                    if "_96_p.mp4" in auth_url:
                        auth_url = auth_url.replace("_96_p.mp4", "_320.mp4")
                    return auth_url
        except Exception:
            pass
        
        # 2. Cara Fallback (Manual Convert dari Preview URL)
        # Berguna jika generateAuthToken gagal/rate limit
        if preview_url:
            # Ubah: https://preview.saavncdn.com/..._96_p.mp4 
            # Menjadi: https://aac.saavncdn.com/..._320.mp4
            fallback_url = preview_url.replace("preview.saavncdn.com", "aac.saavncdn.com") \
                                      .replace("_96_p.mp4", "_320.mp4") \
                                      .replace("_160_p.mp4", "_320.mp4")
            return fallback_url

        return None
