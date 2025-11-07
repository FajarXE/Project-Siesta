# [GANTI FILE: bot/helpers/buzzheavier_api.py]

import aiohttp
import asyncio
from bot.logger import LOGGER
import os
from urllib.parse import quote
import aiofiles
import re # --- PERBAIKAN: Impor 're' untuk regex ---

class BuzzheavierUploader:
    def __init__(self, token: str, folder_id: str):
        self.token = token
        self.folder_id = folder_id
        self.api_url = "https://w.buzzheavier.com" 
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def upload_file(self, file_path: str, file_name: str = None):
        """
        Mengunggah satu file ke Buzzheavier menggunakan PUT.
        Akan secara otomatis mengganti nama jika file sudah ada.
        """
        if not file_name:
            file_name = os.path.basename(file_path)
        
        # URL encode nama file
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

                        # --- PERBAIKAN: Logika Ganti Nama Otomatis ---
                        if result.get("code") == 400:
                            LOGGER.warning(f"Buzzheavier: File {file_name} sudah ada. Mencoba mengganti nama...")
                            
                            # Pisahkan nama file dan ekstensi
                            # Regex ini menangani "file.flac" dan "file (1).flac"
                            match = re.search(r"(.+?)(?: \((\d+)\))?(\.[^.]+)$", file_name)
                            
                            if match:
                                base_name, num, ext = match.groups()
                                # Jika sudah ada angka (misal "file (1).flac"), tambahkan 1
                                num = int(num) + 1 if num else 2
                                new_file_name = f"{base_name} ({num}){ext}"
                            else:
                                # Jika tidak ada ekstensi (misal, hanya "file")
                                base_name = file_name
                                new_file_name = f"{base_name} (2)"
                            
                            # Panggil ulang fungsi ini secara rekursif dengan nama file baru
                            return await self.upload_file(file_path, new_file_name)
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
            LOGGER.error(f"Buzzheavier: Error saat mengunggah {file_name}: {e}")
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
                # Perbarui status progres
                await user_message.edit(f"Mengunggah ke Buzzheavier...\nLagu {i+1} dari {total}\n`{filename}`")
            except:
                pass 
        
        try:
            link = await uploader.upload_file(filepath, filename)
            links.append(link)
        except Exception as e:
            LOGGER.error(f"Buzzheavier: Gagal mengunggah batch file {filename}: {e}")
            # --- PERBAIKAN: Jangan hentikan seluruh batch karena satu error ---
            links.append(f"Gagal: {filename} (Error: {e})")
            # --- BATAS PERBAIKAN ---
            
    return links
