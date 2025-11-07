# [GANTI FILE: bot/helpers/gofile_api.py]

import aiohttp
import asyncio
from bot.logger import LOGGER
import os
import random # --- PERBAIKAN: Impor 'random' ---

class GofileUploader:
    def __init__(self, token: str, folder_id: str):
        self.token = token
        self.folder_id = folder_id
        self.api_url = "https://api.gofile.io"
        self.upload_server = None

    async def _get_server(self):
        """Mendapatkan server unggahan terbaik yang tersedia."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.api_url}/servers") as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    if data.get("status") == "ok":
                        # --- PERBAIKAN: Pilih server secara acak, bukan yang pertama ---
                        servers_list = data["data"]["servers"]
                        self.upload_server = random.choice(servers_list)["name"]
                        # --- BATAS PERBAIKAN ---
                        LOGGER.info(f"Gofile: Mendapat server unggahan: {self.upload_server}")
                        return True
                    else:
                        raise Exception("Status Gofile API tidak 'ok' saat mencari server.")
        except Exception as e:
            LOGGER.error(f"Gofile: Gagal mendapatkan server: {e}")
            return False

    async def upload_file(self, file_path: str, file_name: str = None):
        """Mengunggah satu file ke Gofile."""
        if not self.upload_server:
            if not await self._get_server():
                raise Exception("Gagal mendapatkan server Gofile untuk unggahan.")

        if not file_name:
            file_name = os.path.basename(file_path)
        
        upload_url = f"https://{self.upload_server}.gofile.io/contents/uploadfile"
        
        data = aiohttp.FormData()
        data.add_field('file',
                       open(file_path, 'rb'),
                       filename=file_name)
        data.add_field('token', self.token)
        data.add_field('folderId', self.folder_id)

        try:
            async with aiohttp.ClientSession() as session:
                # Tambahkan timeout untuk menghindari hang
                async with session.post(upload_url, data=data, timeout=aiohttp.ClientTimeout(total=600)) as resp:
                    
                    if resp.status == 500:
                        LOGGER.error(f"Gofile: Server {self.upload_server} mengembalikan 500 Internal Server Error.")
                        raise Exception(f"Gofile server error (500) pada {self.upload_server}")

                    resp.raise_for_status()
                    result = await resp.json()
                    
                    if result.get("status") == "ok":
                        download_page = result["data"].get("downloadPage")
                        LOGGER.info(f"Gofile: Berhasil mengunggah {file_name} -> {download_page}")
                        return download_page
                    else:
                        raise Exception(f"Gagal mengunggah file: {result.get('status')}")
        except Exception as e:
            LOGGER.error(f"Gofile: Error saat mengunggah {file_name}: {e}")
            # Reset server jika gagal, agar percobaan berikutnya mendapat server baru
            self.upload_server = None
            raise e

# Fungsi helper untuk mengunggah banyak file (batch)
async def gofile_batch_upload(file_list: list, token: str, folder_id: str, user_message=None):
    """
    Mengunggah daftar file ke Gofile secara sekuensial dan mengembalikan list link.
    file_list diharapkan berisi 'filepath' dan 'filename' (opsional).
    """
    uploader = GofileUploader(token, folder_id)
    links = []
    total = len(file_list)
    
    for i, file_info in enumerate(file_list):
        filepath = file_info.get('filepath')
        filename = file_info.get('filename') # Anda bisa buat ini dari metadata
        
        if not filename:
             filename = os.path.basename(filepath)

        if user_message:
            try:
                await user_message.edit(f"Mengunggah ke Gofile...\nLagu {i+1} dari {total}\n`{filename}`")
            except:
                pass # Abaikan jika edit gagal
        
        try:
            link = await uploader.upload_file(filepath, filename)
            links.append(link)
        except Exception as e:
            LOGGER.error(f"Gofile: Gagal mengunggah batch file {filename}: {e}")
            links.append(f"Gagal: {filename}")
            
    return links
