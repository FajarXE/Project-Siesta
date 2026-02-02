# [GANTI FILE: bot/helpers/qobuz/qopy.py]

import time
import hashlib
import aiohttp
import aiolimiter
import json
import os
import traceback
import asyncio

from config import Config
from .bundle import Bundle
from bot.logger import LOGGER

# File Database JSON untuk menyimpan Quality + Kredensial User
QOBUZ_USER_DB = "qobuz_user_data.json"

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
        self.quality = 6 # Default 6 (Lossless)
        
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
            unix = int(time.time())
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
            unix = int(time.time())
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            
            if int(fmt_id) not in (5, 6, 7, 27):
                LOGGER.warning(f"QOBUZ: Format ID {fmt_id} tidak valid, fallback ke 6 (Lossless).")
                fmt_id = 6
            
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
                        raise Exception('QOBUZ : Kredensial tidak valid.')
                    elif r.status == 400:
                        raise Exception("QOBUZ : Invalid App ID/Request. Cek kembali User ID dan Token.")
                
                if r.status == 403:
                    raise Exception(f"{r.status}, message='Forbidden / Geo-blocked', url='{r.url}'")
                
                try:
                    return await r.json()
                except aiohttp.ContentTypeError:
                    LOGGER.error(f"QOBUZ: Respons bukan JSON diterima dari {epoint} (Status: {r.status})")
                    return None

    async def multi_meta(self, epoint, key, id, type):
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
                        LOGGER.warning(f"QOBUZ Info: Respons untuk {epoint} tidak memiliki kunci '{type}'.")
                        yield {type: {'items': [], key: 0}}
                        return
                else:
                    j_iterable = j

                if offset == 0:
                    total_items = j_iterable.get(key)
                    if total_items is None:
                        yield j 
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
            raise Exception("QOBUZ : No credentials provided.")
        
        if not usr_info:
            raise Exception("QOBUZ : Gagal login, respons API kosong.")
            
        if not usr_info.get("user"):
             raise Exception(f"QOBUZ : Gagal login. Respons: {usr_info}")

        if not usr_info["user"].get("credential") or not usr_info["user"]["credential"].get("parameters"):
            raise Exception("QOBUZ : Akun Free tidak dapat mendownload track.")
        
        self.uat = usr_info["user_auth_token"]
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        
        # Override user_id jika login via email, untuk referensi
        if not self.user_id:
            self.user_id = usr_info["user"]["id"]

        user_identifier = self.email or self.user_id
        LOGGER.info(f"QOBUZ : Login sebagai {user_identifier}. Status: {self.label}")

    async def test_secret(self, sec):
        test_epoint = "track/getFileUrl"
        unix = int(time.time())
        # Track ID Random untuk test sign
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
            LOGGER.debug(f"Test Secret Failed: {e}")
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
        try:
            u_id = str(user.get("user_id", 0))
        except:
            u_id = "0"

        # Cek kualitas di Manager
        quality = self.quality
        try:
            # Akses instance manager global
            db_data = qobuz_manager._read_db()
            user_data = db_data.get(u_id, {})
            # Prioritas: Setting user > Default Client
            quality = user_data.get("quality", self.quality)
        except Exception as e:
            LOGGER.warning(f"Gagal membaca kualitas dari DB: {e}")

        LOGGER.info(f"QOBUZ: Get URL Track {id} | User {u_id} | Qual {quality}")
        return await self.api_call("track/getFileUrl", id=id, fmt_id=quality)

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

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()


# ==========================================
# QOBUZ MANAGER (MULTI-USER AUTHENTICATION)
# ==========================================

class QobuzManager:
    def __init__(self):
        self.db_file = QOBUZ_USER_DB
        # Cache sesi aktif: {tg_user_id: [QoClient1, QoClient2, ...]}
        self.user_clients = {} 

    def _read_db(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _write_db(self, data):
        try:
            with open(self.db_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            LOGGER.error(f"QOBUZ DB Error: {e}")

    async def add_user_account(self, tg_user_id, q_user_id, q_token):
        """Menambahkan akun ke daftar akun user (Mendukung Multi-Akun)."""
        temp_client = QoClient(user_id=q_user_id, user_token=q_token)
        try:
            # 1. Cek Validitas Login
            await temp_client.login()
            
            tg_user_id = str(tg_user_id)
            db_data = self._read_db()
            
            if tg_user_id not in db_data:
                db_data[tg_user_id] = {}
            
            # Pastikan kunci 'accounts' ada dan berupa list
            if 'accounts' not in db_data[tg_user_id]:
                db_data[tg_user_id]['accounts'] = []
            
            # 2. Cek Duplikasi (Agar tidak menyimpan akun yang sama berkali-kali)
            existing_accounts = db_data[tg_user_id]['accounts']
            for acc in existing_accounts:
                if acc['user_id'] == str(q_user_id):
                    # Jika ada, update token-nya saja
                    acc['token'] = q_token
                    acc['label'] = temp_client.label
                    self._write_db(db_data)
                    # Tutup temp client karena kita hanya butuh verifikasi
                    await temp_client.close_session()
                    return True, f"Akun {temp_client.label} berhasil diperbarui!"

            # 3. Jika baru, tambahkan ke list
            new_account = {
                "user_id": str(q_user_id),
                "token": q_token,
                "label": temp_client.label
            }
            db_data[tg_user_id]['accounts'].append(new_account)
            
            self._write_db(db_data)
            await temp_client.close_session()
            
            # Reset cache user ini agar dimuat ulang saat request berikutnya
            if tg_user_id in self.user_clients:
                # Tutup sesi lama di cache sebelum dihapus dari memori
                for c in self.user_clients[tg_user_id]:
                    await c.close_session()
                del self.user_clients[tg_user_id]
            
            return True, f"Akun ditambahkan! Total akun Anda: {len(db_data[tg_user_id]['accounts'])}"
        except Exception as e:
            if temp_client.session:
                await temp_client.close_session()
            return False, f"Login Gagal: {str(e)}"

    async def remove_specific_account(self, tg_user_id, target_q_uid):
        """Menghapus SATU akun spesifik dari list user."""
        tg_user_id = str(tg_user_id)
        target_q_uid = str(target_q_uid)
        
        db_data = self._read_db()
        
        if tg_user_id in db_data and 'accounts' in db_data[tg_user_id]:
            original_list = db_data[tg_user_id]['accounts']
            
            # Filter: Ambil semua akun KECUALI yang target_q_uid
            new_list = [acc for acc in original_list if str(acc['user_id']) != target_q_uid]
            
            # Jika ada perubahan (artinya ada yang dihapus)
            if len(new_list) < len(original_list):
                db_data[tg_user_id]['accounts'] = new_list
                self._write_db(db_data)
                
                # Update Cache: Tutup sesi klien spesifik tersebut jika aktif di memori
                if tg_user_id in self.user_clients:
                    active_clients = self.user_clients[tg_user_id]
                    remaining_clients = []
                    for client in active_clients:
                        if str(client.user_id) == target_q_uid:
                            await client.close_session()
                        else:
                            remaining_clients.append(client)
                    self.user_clients[tg_user_id] = remaining_clients
                
                return True
                
        return False

    async def remove_all_accounts(self, tg_user_id):
        """Menghapus SEMUA akun milik user tersebut."""
        tg_user_id = str(tg_user_id)
        
        # Tutup sesi aktif jika ada
        if tg_user_id in self.user_clients:
            for client in self.user_clients[tg_user_id]:
                await client.close_session()
            del self.user_clients[tg_user_id]
        
        # Hapus dari DB
        db_data = self._read_db()
        if tg_user_id in db_data and 'accounts' in db_data[tg_user_id]:
            del db_data[tg_user_id]['accounts']
            self._write_db(db_data)
            return True
        return False

    def has_private_session(self, tg_user_id):
        tg_user_id = str(tg_user_id)
        db_data = self._read_db()
        # True jika list 'accounts' ada dan tidak kosong
        return tg_user_id in db_data and db_data[tg_user_id].get('accounts')

    async def get_user_clients(self, tg_user_id):
        """Mengambil SEMUA klien aktif milik user."""
        tg_user_id = str(tg_user_id)
        
        # 1. Cek Cache Memory
        if tg_user_id in self.user_clients:
            # Pastikan sesi belum closed
            active_clients = [c for c in self.user_clients[tg_user_id] if c.session and not c.session.closed]
            if active_clients:
                return active_clients
        
        # 2. Cek Database
        db_data = self._read_db()
        loaded_clients = []
        
        if tg_user_id in db_data and 'accounts' in db_data[tg_user_id]:
            account_list = db_data[tg_user_id]['accounts']
            
            for acc in account_list:
                client = QoClient(user_id=acc['user_id'], user_token=acc['token'])
                try:
                    await client.login()
                    # Override label agar terlihat di log bot
                    client.label = f"{client.label} (Pribadi)"
                    loaded_clients.append(client)
                except Exception as e:
                    LOGGER.error(f"Gagal login akun user {tg_user_id} (ID: {acc['user_id']}): {e}")
            
            if loaded_clients:
                self.user_clients[tg_user_id] = loaded_clients
                return loaded_clients
        
        return []

    async def setup_quality(self, tg_user_id, quality):
        tg_user_id = str(tg_user_id)
        db_data = self._read_db()
        if tg_user_id not in db_data:
            db_data[tg_user_id] = {}
        db_data[tg_user_id]['quality'] = int(quality)
        self._write_db(db_data)

# Instance Global
qobuz_manager = QobuzManager()
