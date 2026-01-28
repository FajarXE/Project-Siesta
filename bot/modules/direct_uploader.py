import os
import aiohttp
import asyncio
import pycurl
import requests
from contextlib import suppress
from io import BufferedReader, BytesIO
from json import JSONDecodeError, loads
from os import path as ospath
from os import walk
from pathlib import Path
from re import search as re_search
from re import sub as re_sub
from time import time
from traceback import format_exc
from typing import Any
from urllib.parse import quote

from aiofiles.os import path as aiopath
from aiohttp import ClientSession

# --- MODIFIKASI: Menggunakan Config dan Logger dari bot Anda, bukan crossx ---
from config import Config
from bot.logger import LOGGER

# Fungsi helper sederhana jika belum ada di utils
def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)} {["B", "KB", "MB", "GB", "TB", "PB"][index]}'
    except IndexError:
        return 'File too large'

def get_mime_type(file_path):
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type or "application/octet-stream"

# Helper async wrapper
async def sync_to_async(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

def async_to_sync(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(func(*args, **kwargs))
# ---------------------------------------------------------------------------

async def limit_checker_ddl(size, listener, isPdrain=False, isGofile=False):
    # Menggunakan Config Environment variables
    # Pastikan variable ini ada di Config.py atau .env jika ingin menggunakan limit
    # Untuk sekarang kita gunakan getattr untuk menghindari error jika config tidak ada
    limit_exceeded = ""
    
    PDRAIN_UP_LIMIT = getattr(Config, 'PDRAIN_UP_LIMIT', 0)
    GOFILE_UP_LIMIT = getattr(Config, 'GOFILE_UP_LIMIT', 0)

    if isPdrain:
        if PDRAIN_UP_LIMIT:
            limit = PDRAIN_UP_LIMIT * 1024**3
            if size > limit:
                limit_exceeded = f"PixelDrain Limit upload is {get_readable_file_size(limit)}"
    elif isGofile:
        if GOFILE_UP_LIMIT:
            limit = GOFILE_UP_LIMIT * 1024**3
            if size > limit:
                limit_exceeded = f"Gofile Limit upload is {get_readable_file_size(limit)}"
    
    if limit_exceeded:
        return f"{limit_exceeded}.\nYour File/Folder size is {get_readable_file_size(size)}"


class Progress(BufferedReader):  # ignore
    def __init__(self, file_name, callback=None):
        super().__init__(open(file_name, "rb"))
        self.__callback = callback
        self.length = Path(file_name).stat().st_size

    def read(self, size=None):
        size = size or (self.length - self.tell())
        if self.__callback:
            self.__callback(self.tell())
        return super().read(size)


class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.__processed_bytes = 0
        self._last_uploaded = 0
        self.__listener = listener
        self.__path = path
        self.__start_time = time()
        self.__total_files = 0
        self.__total_folders = 0
        self.is_cancelled = False
        self.__is_errored = False
        self.__session = None
        
        # Listener user_dict diharapkan dikirim dari caller
        self.__servers = self.__listener.user_dict
        self.__details = self.__listener.extra_details
        self.__logger = LOGGER
        self._pycurl = pycurl.Curl()
        self.__engine = ""
        self.token = None
        self.custom_folder_id = ""
        self.api_url = ["https://api.gofile.io/", "pixeldrain.com"]

    def __progress_callback(self, dl_t, dl_d, upl_t, upl_d):
        if self.is_cancelled:
            return 1
        chunk_size = upl_d - self._last_uploaded
        self._last_uploaded = upl_d
        self.__processed_bytes += chunk_size
        return 0

    async def __resp_handler(self, response: dict):
        if (api_resp := response.get("status", "")) == "ok":
            return response["data"]
        self.__logger.error("resp_handler #error")
        self.__logger.warning(response)
        raise Exception(
            api_resp.split("-")[1]
            if "error-" in api_resp
            else "Response Status is not ok and Reason is Unknown"
        )

    async def __getAccount(self, check_account=False):
        if self.token is None:
            raise Exception

        async with ClientSession() as session:
            async with session.get(
                f"{self.api_url[0]}accounts/getid?token={self.token}"
            ) as resp:
                res = await resp.json()
                if res["status"] == "ok":
                    acc_id = res["data"]["id"]
                    async with session.get(
                        f"{self.api_url[0]}accounts/{acc_id}?token={self.token}"
                    ) as resp2:
                        res2 = await resp2.json()
                        return (
                            res2["status"] == "ok"
                            if check_account
                            else await self.__resp_handler(res2)
                        )

    async def create_folder(self, parentFolderId, folderName):
        if self.token is None:
            raise Exception("Invalid Gofile API Key, Recheck your account !!")

        async with ClientSession() as session:
            async with session.post(
                url=f"{self.api_url[0]}contents/createFolder",
                data={
                    "token": self.token,
                    "parentFolderId": parentFolderId,
                    "folderName": folderName,
                },
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def __setOptions(self, contentId, option, value):
        if self.token is None:
            raise Exception("Invalid Gofile API Key, Recheck your account !!")

        if option not in [
            "name",
            "description",
            "tags",
            "public",
            "expiry",
            "password",
        ]:
            raise Exception(f"Invalid GoFile Option Specified : {option}")
        async with ClientSession() as session:
            async with session.put(
                url=f"{self.api_url[0]}contents/{contentId}/update",
                data={
                    "token": self.token,
                    "attribute": option,
                    "attributeValue": value,
                },
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def gofile_upload_folder(self, path, folderId=None):
        if not await aiopath.isdir(path):
            raise Exception(f"Path: {path} is not a valid directory")

        if not self.custom_folder_id:
            folder_data = await self.create_folder(
                (await self.__getAccount())["rootFolder"], ospath.basename(path)
            )
        else:
            folder_data = await self.create_folder(
                self.custom_folder_id, ospath.basename(path)
            )
        # self.__logger.info(folder_data)
        await self.__setOptions(
            contentId=folder_data["id"], option="public", value="true"
        )

        folderId = folderId or folder_data["id"]
        folder_ids = {".": folderId}
        total_files = 0
        total_folders = 0
        for root, directory, files in await sync_to_async(walk, path):
            total_files += len(files)
            total_folders += len(directory)
            self.__total_files = total_files
            self.__total_folders = total_folders
            rel_path = ospath.relpath(root, path)
            if rel_path == ".":
                parentFolderId = folderId
                currFolderId = folderId
            else:
                parentFolderId = folder_ids.get(ospath.dirname(rel_path), folderId)
                folder_name = ospath.basename(rel_path)
                currFolderId = (await self.create_folder(parentFolderId, folder_name))[
                    "id"
                ]
                await self.__setOptions(
                    contentId=currFolderId, option="public", value="true"
                )
                folder_ids[rel_path] = currFolderId

            for file in files:
                file_path = ospath.join(root, file)
                await sync_to_async(
                    self.gofile_upload, path=file_path, folderId=currFolderId
                )

        self._pycurl.close()
        return folder_data["code"]

    def gofile_upload(
        self,
        path: str,
        folderId: str = "",
        description: str = "",
        password: str = "",
        tags: str = "",
        expire: str = "",
    ):
        if password and len(password) < 4:
            raise ValueError("Password Length must be greater than 4")

        response_buffer = BytesIO()
        isfolder = False
        ca_cert_path = "/etc/ssl/certs/ca-certificates.crt"
        self._pycurl.setopt(
            self._pycurl.URL, "https://upload.gofile.io/contents/uploadfile"
        )
        self._pycurl.setopt(pycurl.CAINFO, ca_cert_path)
        self._pycurl.setopt(
            self._pycurl.HTTPHEADER, ["Authorization: Bearer " + self.token]
        )

        self._pycurl.setopt(self._pycurl.POST, 1)
        self._pycurl.setopt(self._pycurl.WRITEDATA, response_buffer)
        self._pycurl.setopt(self._pycurl.NOPROGRESS, False)
        self._pycurl.setopt(self._pycurl.XFERINFOFUNCTION, self.__progress_callback)
        if self.custom_folder_id:
            self._pycurl.setopt(
                self._pycurl.HTTPPOST,
                [
                    ("folderId", self.custom_folder_id),
                    ("file", (self._pycurl.FORM_FILE, f"{path}".encode())),
                ],
            )
        elif folderId:
            isfolder = True
            self._pycurl.setopt(
                self._pycurl.HTTPPOST,
                [
                    ("folderId", folderId),
                    ("file", (self._pycurl.FORM_FILE, f"{path}".encode())),
                ],
            )
        else:
            self._pycurl.setopt(
                self._pycurl.HTTPPOST,
                [("file", (self._pycurl.FORM_FILE, f"{path}".encode()))],
            )
        if description:
            self._pycurl.setopt(self._pycurl.HTTPPOST, [("description", description)])
        if password:
            self._pycurl.setopt(self._pycurl.HTTPPOST, [("password", password)])
        if tags:
            self._pycurl.setopt(self._pycurl.HTTPPOST, [("tags", tags)])
        if expire:
            self._pycurl.setopt(self._pycurl.HTTPPOST, [("expire", expire)])

        self._last_uploaded = 0
        try:
            self._pycurl.perform()
        except pycurl.error as e:
            if self.is_cancelled:
                return
            self._pycurl.close()
            self.__logger.error(f"GF_UPLOAD.pycurl.error: {e}")
            raise Exception(f"GF_UPLOAD.pycurl.error: {e}")
        except Exception as e:
            self._pycurl.close()
            self.__logger.error(f"GF_UPLOAD: {e}")
            raise Exception(f"GF_UPLOAD: {e}")

        response_data = response_buffer.getvalue()
        if not response_data:
            self._pycurl.close()
            raise Exception("No File to Upload. response_data is None")

        try:
            result = loads(response_data.decode())
        except JSONDecodeError:
            self._pycurl.close()
            raise Exception("ERROR: Json Response.")
        if isfolder and not self.is_cancelled:
            return
        elif result:
            return async_to_sync(self.__resp_handler, result)
        else:
            raise Exception(f"ERROR: {result.get('message')}")

    # --- BAGIAN PIXELDRAIN & LAINNYA DIHAPUS UNTUK MENYINGKAT, FOKUS KE GOFILE ---
    # Jika Anda membutuhkan provider lain, Anda bisa menambahkannya kembali dari file asli
    # dengan menyesuaikan import TG.bot.log menjadi LOGGER

    async def __upload_to_ddl(self, file_path, size, upload_type):
        all_links = {}
        if upload_type in ("gofile", "gf"):
            if limit := await limit_checker_ddl(size, self.__listener, isGofile=True):
                self.is_cancelled = True
                return await self.__listener.onUploadError(limit)
            self.__engine += "Gofile"
            key = "gofile"
            self.token = self.__servers.get(key, {}).get("api", "")
            if not self.token:
                raise Exception(f"{key} api key None!")
            self.custom_folder_id = self.__servers.get(key, {}).get("folder_id", "")
            if await aiopath.isfile(file_path):
                if (
                    gCode := await sync_to_async(self.gofile_upload, path=file_path)
                ) and gCode.get("downloadPage", {}):
                    self._pycurl.close()
                    all_links["Gofile"] = gCode["downloadPage"]
            if await aiopath.isdir(file_path):
                if gCode := await self.gofile_upload_folder(path=file_path):
                    self._pycurl.close()
                    all_links["Gofile"] = f"https://gofile.io/d/{gCode}"

        if not all_links:
            raise Exception("No DirectUpload Enabled to Upload.")
        return all_links

    async def upload(self, file_name, size, upload_type):
        item_path = f"{self.__path}/{file_name}"
        self.__logger.info(f"Uploading: {item_path} via DirectUpload")

        if self.is_cancelled:
            return
        try:
            if await aiopath.isfile(item_path):
                mime_type = get_mime_type(item_path)
            else:
                mime_type = "Folder"
            link = await self.__upload_to_ddl(item_path, size, upload_type)
            if not link:
                self._pycurl.close()
                raise Exception("Upload has been manually cancelled!")
            if self.is_cancelled:
                return
            self._pycurl.close()
            self.__logger.info(f"Uploaded with DirectUpload: {item_path}")
            return link # RETURN DICT LINKS
        except Exception as err:
            self.__logger.info("DirectUpload has been Cancelled")
            if self.__session:
                await self.__session.close()
            self._pycurl.close()
            if self.is_cancelled:
                return
            err = str(err).replace(">", "").replace("<", "")
            self.__logger.info(format_exc())
            await self.__listener.onUploadError(err)
            self.__is_errored = True
        finally:
            if self.is_cancelled or self.__is_errored:
                return
            self._pycurl.close()
            if self.__session:
                await self.__session.close()
