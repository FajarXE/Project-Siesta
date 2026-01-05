import aiohttp
import hashlib
import time
import logging
from urllib.parse import urlencode

LOGGER = logging.getLogger(__name__)

class LivePhishApi:
    def __init__(self):
        # Kunci API Sesuai Go Code
        self.client_id = "Fujeij8d764ydxcnh4676scsr7f4"
        self.developer_key = "njeurd876frhdjxy6sxxe721"
        self.sig_key = "jdfirj8475jf_"
        
        # User Agent Utama (Sama persis dengan Go const userAgent)
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

    def _generate_sig(self, offset=0):
        # Sama dengan Go: time.Now().Unix() + epochComp
        timestamp = str(int(time.time()) + offset)
        raw = self.sig_key + timestamp
        sig = hashlib.md5(raw.encode('utf-8')).hexdigest()
        return sig, timestamp

    async def _request(self, method, url, **kwargs):
        async with self.session.request(method, url, **kwargs) as resp:
            try:
                # Paksa baca JSON (Go tidak peduli content-type, Python strict)
                return await resp.json(content_type=None)
            except Exception:
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
        
        LOGGER.info(f"LivePhish Login OK. ID: {sub_info.get('subscriptionID')}, CanStream: {sub_info.get('canStreamSubContent')}")

        if not sub_info.get("canStreamSubContent"):
            LOGGER.warning("Warning: Akun ini mungkin tidak memiliki akses streaming aktif.")

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
        # 1. Coba kualitas utama
        url = await self._fetch_stream_with_retries(track_id, quality_code)
        
        # 2. Fallback ke AAC jika FLAC gagal (Sama seperti logika Go yang mencoba format lain jika gagal)
        if not url and quality_code in ["FLAC", "ALAC"]:
            LOGGER.warning(f"LivePhish: Gagal {quality_code}, mencoba fallback ke AAC...")
            url = await self._fetch_stream_with_retries(track_id, "AAC")
            
        return url

    async def _fetch_stream_with_retries(self, track_id, quality_code):
        # Mapping Sesuai Go Code (func parseCfg)
        # 1 -> 4 (AAC), 2 -> 2 (ALAC), 3 -> 3 (FLAC)
        platform_map = {"AAC": "4", "ALAC": "2", "FLAC": "3"}
        platform_id = platform_map.get(quality_code, "4")
        
        # PENTING: User-Agent HARUS "LivePhishAndroid" saat minta stream (Lihat main.go baris 191)
        # Jangan pakai self.user_agent yang panjang di sini.
        headers = {"User-Agent": "LivePhishAndroid"}

        # Epoch Compensation (Sama seperti Go flag -epochCompensation)
        # Mencoba rentang waktu jika jam server tidak sinkron
        offsets = [0, 5, -5, 10, -10, 15, -15, 30, -30]
        
        last_js_response = None

        for offset in offsets:
            sig, timestamp = self._generate_sig(offset)
            
            params = {
                "trackID": str(track_id),
                "app": "1", # Sesuai Go Code
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
                if offset != 0:
                    LOGGER.info(f"LivePhish: Stream OK dengan Time Offset {offset}s.")
                return link
            
            last_js_response = js
        
        LOGGER.error(f"LivePhish Stream Fail (ID: {track_id}, Q: {quality_code}). Last Resp: {last_js_response}")
        return None
