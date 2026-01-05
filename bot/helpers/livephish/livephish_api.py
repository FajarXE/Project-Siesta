import aiohttp
import hashlib
import time
import json
from urllib.parse import urlencode

class LivePhishApi:
    def __init__(self):
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
        # Porting dari Go: generateSig
        # timestamp + epoch compensation (kita pakai standar time.time())
        timestamp = str(int(time.time()))
        raw = self.sig_key + timestamp
        sig = hashlib.md5(raw.encode('utf-8')).hexdigest()
        return sig, timestamp

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
                raise Exception(f"Login Step 1 Failed: {resp.status}")
            js = await resp.json()
            self.access_token = js.get("access_token")

        # 2. Get User Token (secureApi.aspx)
        params = {
            "method": "session.getUserToken",
            "clientID": self.client_id,
            "developerKey": self.developer_key,
            "user": email,
            "pw": password
        }
        async with self.session.get(self.api_base + "secureApi.aspx", params=params, headers={"User-Agent": self.user_agent}) as resp:
            js = await resp.json()
            self.user_token = js.get("Response", {}).get("tokenValue")

        # 3. Get Subscriber Info (untuk Stream Params)
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
        async with self.session.get(self.api_base + "secureApi.aspx", params=params, headers=headers_auth) as resp:
            js = await resp.json()
            sub_info = js.get("Response", {}).get("subscriptionInfo", {})
            
            if not sub_info.get("canStreamSubContent"):
                raise Exception("Akun tidak memiliki langganan aktif (canStreamSubContent=False).")

            # Simpan parameter penting untuk streaming (Porting struct StreamParams)
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
        async with self.session.get(self.api_base + "api.aspx", params=params, headers={"User-Agent": self.user_agent}) as resp:
            return await resp.json()

    async def get_stream_url(self, track_id, quality_code):
        # Quality Mapping dari Go:
        # 1 (AAC) -> platform 4
        # 2 (ALAC) -> platform 2
        # 3 (FLAC) -> platform 3
        platform_map = {
            "AAC": "4",
            "ALAC": "2",
            "FLAC": "3"
        }
        platform_id = platform_map.get(quality_code, "4") # Default AAC

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
        
        # Header khusus untuk streaming (dari Go code)
        headers = {"User-Agent": "LivePhishAndroid"}
        
        async with self.session.get(self.api_base + "bigriver/subPlayer.aspx", params=params, headers=headers) as resp:
            js = await resp.json()
            return js.get("streamLink")
