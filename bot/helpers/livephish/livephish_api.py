# [GANTI FILE: bot/helpers/livephish/livephish_api.py]

import aiohttp
import hashlib
import time
import logging
from urllib.parse import urlencode

LOGGER = logging.getLogger(__name__)

class LivePhishApi:
    def __init__(self):
        # Kunci API 
        self.client_id = "Fujeij8d764ydxcnh4676scsr7f4"
        self.developer_key = "njeurd876frhdjxy6sxxe721"
        self.sig_key = "jdfirj8475jf_"
        
        # User Agent Browser Biasa (Bukan Android App) agar lebih stabil
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        self.api_base = "https://www.livephish.com/"
        self.api_base_id = "https://id.livephish.com/connect/"
        
        self.session = aiohttp.ClientSession()
        self.access_token = None
        self.user_token = None
        self.stream_params = {}
        self.user_id = None

    async def close(self):
        await self.session.close()

    def _generate_sig(self, offset=0):
        # Epoch dalam milidetik atau detik? Kode Go pakai detik.
        # Kita coba pakai detik.
        timestamp = str(int(time.time()) + offset)
        raw = self.sig_key + timestamp
        sig = hashlib.md5(raw.encode('utf-8')).hexdigest()
        return sig, timestamp

    async def _request(self, method, url, **kwargs):
        async with self.session.request(method, url, **kwargs) as resp:
            try:
                return await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                LOGGER.error(f"LivePhish API Non-JSON: {text[:200]}")
                return {"error": True, "raw": text}

    async def login(self, email, password):
        # 1. OAuth Token
        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "client_id": self.client_id,
            "grant_type": "password",
            "scope": "offline_access nugsnet:api nugsnet:legacyapi",
            "username": email,
            "password": password
        }
        
        async with self.session.post(self.api_base_id + "token", data=data, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Login Step 1 Failed: {resp.status} - {text}")
            js = await resp.json()
            self.access_token = js.get("access_token")

        # 2. Get User Token
        params = {
            "method": "session.getUserToken",
            "clientID": self.client_id,
            "developerKey": self.developer_key,
            "user": email,
            "pw": password
        }
        js = await self._request("GET", self.api_base + "secureApi.aspx", params=params, headers={"User-Agent": self.user_agent})
        self.user_token = js.get("Response", {}).get("tokenValue")

        # 3. Get Subscriber Info
        params = {
            "method": "user.getSubscriberInfo",
            "developerKey": self.developer_key,
            "user": email,
            "token": self.user_token
        }
        headers_auth = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": self.user_agent
        }
        js = await self._request("GET", self.api_base + "secureApi.aspx", params=params, headers=headers_auth)
        sub_info = js.get("Response", {}).get("subscriptionInfo", {})
        
        can_stream = sub_info.get("canStreamSubContent")
        LOGGER.info(f"LivePhish Login OK. UserID: {sub_info.get('userID')}, CanStream: {can_stream}")

        self.stream_params = {
            "subscriptionID": str(sub_info.get("subscriptionID")),
            "subCostplanIDAccessList": str(sub_info.get("subCostplanIDAccessList")),
            "userID": str(sub_info.get("userID")),
            "startDateStamp": str(sub_info.get("startDateStamp")),
            "endDateStamp": str(sub_info.get("endDateStamp"))
        }
        self.user_id = self.stream_params["userID"]
        return True

    async def get_album_meta(self, album_id):
        params = {
            "method": "catalog.container",
            "containerID": album_id,
            "vdisp": "1"
        }
        return await self._request("GET", self.api_base + "api.aspx", params=params, headers={"User-Agent": self.user_agent})

    async def get_stream_url(self, track_id, quality_code):
        # Coba kualitas utama
        url = await self._fetch_stream_with_retries(track_id, quality_code)
        
        # Fallback
        if not url and quality_code in ["FLAC", "ALAC"]:
            LOGGER.warning(f"LivePhish: Gagal {quality_code}, fallback AAC...")
            url = await self._fetch_stream_with_retries(track_id, "AAC")
            
        return url

    async def _fetch_stream_with_retries(self, track_id, quality_code):
        # --- PERUBAHAN PENTING: MAPPING PLATFORM ---
        # Platform ID 0 sering digunakan untuk Web Player (lebih kompatibel)
        # 3 = FLAC (Web/App), 4 = AAC
        
        platform_id = "0" # Default Web
        if quality_code == "FLAC":
            platform_id = "3" 
        elif quality_code == "ALAC":
            platform_id = "2"
        else: # AAC
            platform_id = "4" # Atau coba 0 jika 4 gagal

        # Gunakan User-Agent Browser
        headers = {"User-Agent": self.user_agent}

        # Offset waktu yang dicoba
        offsets = [0, -1, 1, -2, 2, -5, 5]
        
        last_js_response = None

        for offset in offsets:
            sig, timestamp = self._generate_sig(offset)
            
            # --- PERUBAHAN PENTING: PARAMETER APP ---
            # app=3 sering digunakan untuk Web Player
            params = {
                "trackID": str(track_id),
                "app": "3", # Ganti dari 1 ke 3
                "platformID": platform_id,
                "subscriptionID": self.stream_params["subscriptionID"],
                "subCostplanIDAccessList": self.stream_params["subCostplanIDAccessList"],
                "nn_userID": self.stream_params["userID"],
                "startDateStamp": self.stream_params["startDateStamp"],
                "endDateStamp": self.stream_params["endDateStamp"],
                "tk": sig,
                "lxp": timestamp
            }
            
            js = await self._request("GET", self.api_base + "bigriver/subPlayer.aspx", params=params, headers=headers)
            link = js.get("streamLink")
            
            if link:
                return link
            
            last_js_response = js
        
        LOGGER.error(f"LivePhish Stream Fail (ID: {track_id}, Q: {quality_code}). Last Resp: {last_js_response}")
        return None
