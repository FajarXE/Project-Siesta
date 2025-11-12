# [GANTI FILE: bot/helpers/qobuz/qopy.py]

# From vitiko98/qobuz-dl
import time
import hashlib
import aiohttp
import aiolimiter

from config import Config

from .bundle import Bundle

from bot.logger import LOGGER

class QoClient:
    def __init__(self, email=None, password=None, user_id=None, user_token=None):
        self.email = email
        self.password = password
        self.user_id = user_id
        self.user_token = user_token
        self.uat = None
        self.label = None
        self.sec = None
        self.id = None
        self.secrets = None
        self.session = None
        self.ratelimit = aiolimiter.AsyncLimiter(30, 60)
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.quality = 6
        self.user_data = {}

    async def api_call(self, epoint, **kwargs):
        if epoint == "user/login":
            if kwargs.get('email'):
                params = {
                    "email": kwargs["email"],
                    "password": kwargs["pwd"],
                    "app_id": self.id,
                }
            else:
                params = {
                    "user_id": kwargs["userid"],
                    "user_auth_token": kwargs["usertoken"],
                    "app_id": self.id,
                }
        elif epoint == "track/get":
            params = {"track_id": kwargs["id"]}
        elif epoint == "album/get":
            params = {"album_id": kwargs["id"]}
        elif epoint == "playlist/get":
            params = {
                "extra": "tracks",
                "playlist_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
            }
        elif epoint == "artist/get":
            params = {
                "app_id": self.id,
                "artist_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "label/get":
            params = {
                "label_id": kwargs["id"],
                "limit": 99999,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "favorite/getUserFavorites":
            unix = time.time()
            r_sig = "favoritegetUserFavorites" + str(unix) + kwargs["sec"]
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "app_id": self.id,
                "user_auth_token": self.uat,
                "type": "albums",
                "request_ts": unix,
                "request_sig": r_sig_hashed,
            }
        elif epoint == "track/getFileUrl":
            unix = time.time()
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (5, 6, 7, 27):
                raise Exception("QOBUZ : Invalid quality id: choose between 5, 6, 7 or 27")
            r_sig = "trackgetFileUrlformat_id{}intentstreamtrack_id{}{}{}".format(
                fmt_id, track_id, unix, kwargs.get("sec", self.sec)
            )
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "request_ts": unix,
                "request_sig": r_sig_hashed,
                "track_id": track_id,
                "format_id": fmt_id,
                "intent": "stream",
            }
        else:
            params = kwargs

        return await self.session_call(epoint, params)

    async def session_call(self, epoint, params):
        async with self.ratelimit:
            async with self.session.get(self.base + epoint, params=params) as r:
                if epoint == "user/login":
                    if r.status == 401:
                        raise Exception('QOBUZ : Invalid credentials given..... Disabling QOBUZ')
                    elif r.status == 400:
                        raise Exception("QOBUZ : Invalid App ID. Please Recheck your credentials.... Disabling QOBUZ")
                elif (
                    epoint in ["track/getFileUrl", "favorite/getUserFavorites"]
                    and r.status == 400
                ):
                    # --- INI ADALAH BARIS YANG MENYEBABKAN CRASH ANDA ---
                    raise Exception("QOBUZ : Invalid App Secret. Please recheck your credentials.... Disabling QOBUZ")
                
                if r.status == 403:
                    raise Exception(f"{r.status}, message='Akses ditolak (Forbidden). Kemungkinan IP server diblokir.', url='{r.url}'")
                
                try:
                    return await r.json()
                except aiohttp.ContentTypeError:
                    LOGGER.error(f"QOBUZ: Respons bukan JSON diterima dari {epoint} (Status: {r.status})")
                    return None # Kembalikan None jika bukan JSON


    # --- FUNGSI DIPERBARUI UNTUK MENGUBAH LEVEL LOG ---
    async def multi_meta(self, epoint, key, id, type):
        # type akan menjadi "tracks" (untuk playlist) atau "albums" (untuk artist/label)
        total = 1
        offset = 0
        while total > 0:
            
            j = await self.api_call(epoint, id=id, offset=offset, type=type)
            
            if j is None:
                LOGGER.error(f"QOBUZ Error: Panggilan API ke {epoint} untuk ID {id} gagal (menerima None).")
                return

            try:
                if type in ["tracks", "albums"]:
                    j_iterable = j.get(type)
                    if j_iterable is None:
                        # --- PERBAIKAN: Ubah dari .error() menjadi .warning() ---
                        LOGGER.warning(f"QOBUZ Info: Respons untuk {epoint} tidak memiliki kunci '{type}'. Mengembalikan hasil kosong.")
                        # --- BATAS PERBAIKAN ---
                        yield {type: {'items': [], key: 0}}
                        return
                else:
                    j_iterable = j

                if offset == 0:
                    total_items = j_iterable.get(key)
                    if total_items is None:
                        # --- PERBAIKAN: Ubah dari .error() menjadi .warning() ---
                        LOGGER.warning(f"QOBUZ Info: Objek respons tidak memiliki kunci total '{key}' di {epoint}. Mengembalikan hasil kosong.")
                        # --- BATAS PERBAIKAN ---
                        yield j # Kembalikan apa yang kita punya, tapi hentikan loop
                        return
                        
                    yield j 
                    total = total_items - 99999
                else:
                    yield j 
                    total -= 99999
                offset += 99999
            
            except Exception as e:
                LOGGER.error(f"QOBUZ Multi-Meta Parsing Gagal untuk {epoint}: {e}")
                return 
    # --- BATAS FUNGSI DIPERBARUI ---
            

    async def auth(self):
        if self.email:
            usr_info = await self.api_call(
                "user/login", 
                email=self.email, 
                pwd=self.password)
        elif self.user_id:
            usr_info = await self.api_call(
                "user/login", 
                userid=self.user_id,
                usertoken=self.user_token)
        else:
            raise Exception("QOBUZ : No credentials (email/password or user_id/token) provided for this client instance.")
        
        if not usr_info:
            # Panggilan API gagal (misal 404/500)
            raise Exception("QOBUZ : Gagal login, respons API kosong.")
            
        if not usr_info.get("user"):
             raise Exception(f"QOBUZ : Gagal login, respons tidak terduga: {usr_info}")

        if not usr_info["user"].get("credential") or not usr_info["user"]["credential"].get("parameters"):
            raise Exception("QOBUZ : Free accounts are not eligible to download tracks from QOBUZ. Disabling QOBUZ for now")
        
        self.uat = usr_info["user_auth_token"]
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        
        user_identifier = self.email or self.user_id
        LOGGER.info(f"QOBUZ : Logged in as {user_identifier}. Membership Status: {self.label}")

    async def test_secret(self, sec):
        test_epoint = "track/getFileUrl"
        unix = time.time()
        
        r_sig = "trackgetFileUrlformat_id5intentstreamtrack_id5966783{}{}".format(unix, sec)
        r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
        
        params = {
            "request_ts": unix,
            "request_sig": r_sig_hashed,
            "track_id": 5966783, 
            "format_id": 5,
            "intent": "stream",
        }
        
        try:
            async with self.ratelimit:
                async with self.session.get(self.base + test_epoint, params=params) as r:
                    if r.status == 200:
                        return True
                    return False
        
        except Exception as e:
            LOGGER.debug(f"Test Secret Failed due to connection/timeout for secret: {e}")
            return False

    def get_tokens(self):
        bundle = Bundle()
        self.id = str(bundle.get_app_id())
        self.secrets = [
            secret for secret in bundle.get_secrets().values() if secret
        ]

    async def login(self):
        self.get_tokens()
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) 
        
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
                "X-App-Id": self.id,
            }
        )
        await self.auth()
        await self.cfg_setup()

    async def cfg_setup(self):
        for secret in self.secrets:
            if not secret:
                continue
            if await self.test_secret(secret):
                self.sec = secret
                break
        if self.sec is None:
            raise Exception("QOBUZ : Can't find any valid app secret") 

    async def get_track_url(self, id, user: dict):
        user_dict = self.user_data.get(user["user_id"], {})
        quality = user_dict.get("qobuz_qual", self.quality)
        fmt_id = quality
        return await self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)

    async def get_album_meta(self, id):
        return await self.api_call("album/get", id=id)

    async def get_track_meta(self, id):
        return await self.api_call("track/get", id=id)

    async def get_artist_meta(self, id):
        res = []
        async for data in self.multi_meta("artist/get", "total", id, "albums"): 
            res.append(data)
        return res

    async def get_plist_meta(self, id):
        res = []
        async for data in self.multi_meta("playlist/get", "total", id, "tracks"): 
            res.append(data)
        return res

    async def get_label_meta(self, id):
        res = []
        async for data in self.multi_meta("label/get", "total", id, "albums"):
            res.append(data)
        return res

    async def setup_quality(self, user_id: int=0, qual: int=0) -> None:
        data = {}
        self.user_data.setdefault(user_id, {})
        if qual:
            data["qobuz_qual"] = qual
        self.user_data[user_id].update(data)

    async def close_session(self):
        """Menutup sesi aiohttp jika ada."""
        if self.session and not self.session.closed:
            await self.session.close()

