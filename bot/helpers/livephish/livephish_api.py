# [GANTI FILE: bot/helpers/livephish/livephish_api.py]

import aiohttp
import hashlib
import time
import json
import logging
from urllib.parse import urlencode

# Logger khusus untuk melihat respons API
LOGGER = logging.getLogger(__name__)

class LivePhishApi:
    def __init__(self):
        # Kunci API dari Go Code
        self.client_id = "Fujeij8d764ydxcnh4676scsr7f4"
        self.developer_key = "njeurd876frhdjxy6sxxe721"
        self.sig_key = "jdfirj8475jf_"
        self.user_agent = "LivePhish/3.4.5.357 (Android; 7.1.2; Asus; ASUS_Z01QD)"
        
        self.api_base = "https://www.livephish.com/"
        self.api_base_id = "https://id.livephish.com/connect/"
        
        self.session = aiohttp.ClientSession()
        self.access_token = None
        self.user_token = None
        self.stream_params = {}
        self.user_id = None

    async def close(self):
        await self.session.close()

    def _generate_sig(self):
        # Timestamp detik saat ini
        timestamp = str(int(time.time()))
        raw = self.sig_key + timestamp
        sig = hashlib.md5(raw.encode('utf-8')).hexdigest()
        return sig, timestamp

    async def _request(self, method, url, **kwargs):
        """Wrapper request untuk menangani text/html response type"""
        async with self.session.request(method, url, **kwargs) as resp:
            try:
                # Paksa baca sebagai JSON meskipun header text/html
                return await resp.json(content_type=None)
            except Exception:
                # Jika gagal JSON, kembalikan teks mentah untuk debug
                text = await resp.text()
                LOGGER.error(f"LivePhish API Error (Non-JSON): {text[:200]}")
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
        # Gunakan wrapper _request
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
        
        # Log info langganan untuk memastikan akun valid
        LOGGER.info(f"LivePhish Sub Info: CanStream={sub_info.get('canStreamSubContent')} Type={sub_info.get('label')}")

        if not sub_info.get("canStreamSubContent"):
            raise Exception("Akun tidak memiliki langganan aktif (canStreamSubContent=False).")

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
        # 1. Coba request dengan kualitas yang diminta
        url = await self._fetch_stream_url(track_id, quality_code)
        
        # 2. Jika gagal dan request awal adalah FLAC/ALAC, coba fallback ke AAC
        if not url and quality_code in ["FLAC", "ALAC"]:
            LOGGER.warning(f"LivePhish: Gagal kualitas {quality_code}, mencoba fallback ke AAC...")
            url = await self._fetch_stream_url(track_id, "AAC")
            
        return url

    async def _fetch_stream_url(self, track_id, quality_code):
        platform_map = {
            "AAC": "4",
            "ALAC": "2",
            "FLAC": "3"
        }
        platform_id = platform_map.get(quality_code, "4")
        sig, timestamp = self._generate_sig()
        
        params = {
            "trackID": str(track_id),
            "app": "1",
            "platformID": platform_id,
            "subscriptionID": self.stream_params["subscriptionID"],
            "subCostplanIDAccessList": self.stream_params["subCostplanIDAccessList"],
            "nn_userID": self.stream_params["userID"],
            "startDateStamp": self.stream_params["startDateStamp"],
            "endDateStamp": self.stream_params["endDateStamp"],
            "tk": sig,
            "lxp": timestamp
        }
        
        headers = {"User-Agent": "LivePhishAndroid"}
        
        # Panggil endpoint stream
        js = await self._request("GET", self.api_base + "bigriver/subPlayer.aspx", params=params, headers=headers)
        
        link = js.get("streamLink")
        
        # --- LOGGING PENTING ---
        if not link:
            # Ini akan mencetak alasan kenapa link kosong (misal: "User not authorized" atau "Invalid Signature")
            LOGGER.error(f"LivePhish Stream Fail (ID: {track_id}, Q: {quality_code}): RESPONSE JSON -> {js}")
        # -----------------------
            
        return link
