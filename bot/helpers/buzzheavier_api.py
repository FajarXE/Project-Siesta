# [GANTI FILE: bot/helpers/buzzheavier_api.py]

import aiohttp
import asyncio
from bot.logger import LOGGER
import os
from urllib.parse import quote
import aiofiles
import re

# --- PERBAIKAN: Tentukan batas percobaan ---
MAX_RENAME_ATTEMPTS = 10
# --- BATAS PERBAIKAN ---

class BuzzheavierUploader:
    def __init__(self, token: str, folder_id: str):
        self.token = token
        self.folder_id = folder_id
        self.api_url = "https://w.buzzheavier.com" 
        self.headers = {"Authorization": f"Bearer {self.token}"}

    # --- PERBAIKAN: Tambahkan parameter retry_count ---
    async def upload_file(self, file_path: str, file_name: str = None, retry_count: int = 0):
        """
        Mengunggah satu file ke Buzzheavier menggunakan PUT.
        Akan secara otomatis mengganti nama jika file sudah ada.
        """
        # --- BATAS PERBAIKAN ---
        
        if not file_name:
            file_name = os.path.basename(file_path)
        
        safe_file_name = quote(file_name)
        upload_url = f"{self.api_url}/{self.folder_id}/{safe_file_name}"
        
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with aiofiles.open(file_path, 'rb') as f:
                    async with session.put(upload_url, data=f) as resp:
                        
                        try:
                            result = await resp.json()
                        except aiohttp.ContentTypeError:
                            LOGGER.error(f"Buzzheavier: Respons bukan JSON. Status: {resp.status}, Teks: {await resp.text()}")
                            raise Exception(f"Respons server tidak valid (Status {resp.status}).")

                        # --- PERBAIKAN: Logika Ganti Nama Otomatis dengan Jeda & Batas ---
                        if result.get("code") == 400:
                            LOGGER.warning(f"Buzzheavier: File {file_name} sudah ada. (Percobaan ke-{retry_count+1})")
                            
                            # Periksa jika kita sudah melewati batas
                            if retry_count >= MAX_RENAME_ATTEMPTS:
                                raise Exception(f"File {file_name} sudah ada dan gagal diunggah setelah {MAX_RENAME_ATTEMPTS} kali ganti nama.")
                            
                            # Tambahkan jeda 1 detik agar tidak dianggap spam
                            await asyncio.sleep(1)

                            match = re.search(r"(.+?)(?: \((\d+)\))?(\.[^.]+)$", file_name)
                            
                            if match:
                                base_name, num, ext = match.groups()
                                num = int(num) + 1 if num else 2
                                new_file_name = f"{base_name} ({num}){ext}"
                            else:
                                base_name = file_name
                                new_file_name = f"{base_name} (2)"
                            
                            # Panggil ulang fungsi dengan nama baru DAN tambahkan hitungan percobaan
                            return await self.upload_file(file_path, new_file_name, retry_count + 1)
                        # --- BATAS PERBAIKAN ---

                        if result.get("code") != 201:
                            resp.raise_for_status() 
                            
                        data = result.get("data")
                        if not data:
                            raise Exception("Respons tidak valid dari Buzzheavier.")
                            
                        file_id = data.get("id")
                        final_link = f"https://buzzheavier.com/{file_id}"
                        LOGGER.info(f"Buzzheavier: Berhasil mengunggah {file_name} -> {final_link}")
                        return final_link

        except aiohttp.ClientResponseError as e:
             LOGGER.error(f"Buzzheavier: Error HTTP saat mengunggah {file_name}: {e.status} - {e.message}")
             raise Exception(f"HTTP {e.status} saat mengunggah: {e.message}")
        except Exception as e:
            # --- PERBAIKAN: Jangan log error jaringan yang diharapkan ---
            if "Connection reset by peer" not in str(e):
                LOGGER.error(f"Buzzheavier: Error saat mengunggah {file_name}: {e}")
            # --- BATAS PERBAIKAN ---
            raise e

# Fungsi helper untuk mengunggah banyak file (batch)
async def buzzheavier_batch_upload(file_list: list, token: str, folder_id: str, user_message=None):
    """
    Mengunggah daftar file ke Buzzheavier secara sekuensial dan mengembalikan list link.
    """
    uploader = BuzzheavierUploader(token, folder_id)
    links = []
    total = len(file_list)
    
    for i, file_info in enumerate(file_list):
        filepath = file_info.get('filepath')
        filename = file_info.get('filename')
        
        if not filename:
             filename = os.path.basename(filepath)

        if user_message:
            try:
                await user_message.edit(f"Mengunggah ke Buzzheavier...\nLagu {i+1} dari {total}\n`{filename}`")
            except:
                pass 
        
        try:
            # Panggil upload_file tanpa retry_count (defaultnya 0)
            link = await uploader.upload_file(filepath, filename)
            links.append(link)
        except Exception as e:
            LOGGER.error(f"Buzzheavier: Gagal mengunggah batch file {filename}: {e}")
            links.append(f"Gagal: {filename} (Error: {e})")
            
    return links
