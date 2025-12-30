import aiohttp
import json
import html

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
            text = await resp.text()
            # Bersihkan response karena kadang ada comment block di JSON
            clean_json = json.loads(text.split('-->')[-1] if '-->' in text else text)
            
            # API kadang mengembalikan dict di dalam dict dengan key random
            if "songs" in clean_json: 
                 return clean_json["songs"][0]
            # Handle format lama/aneh
            key = list(clean_json.keys())[0]
            return clean_json[key]

    async def get_auth_url(self, session: aiohttp.ClientSession, encrypted_url: str):
        params = {
            '__call': 'song.generateAuthToken',
            'url': encrypted_url,
            'bitrate': '320',
            'api_version': '4',
            '_format': 'json',
            'ctx': 'web6dot0',
            '_marker': '0',
        }
        async with session.get(self.base_url, params=params, headers=self.headers) as resp:
            data = await resp.json()
            auth_url = data.get("auth_url")
            if auth_url:
                # Fix extension dari preview ke aac/mp4
                if "preview" in auth_url:
                    auth_url = auth_url.replace("preview", "aac")
                if "_96_p.mp4" in auth_url:
                    auth_url = auth_url.replace("_96_p.mp4", "_320.mp4")
                return auth_url
            return None
