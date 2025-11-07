# [FILE BARU: bot/helpers/buzzheavier_api.py]

import aiohttp
import asyncio
from bot.logger import LOGGER
import os
from urllib.parse import quote

class BuzzheavierUploader:
    def __init__(self, token: str, folder_id: str):
        self.token = token
        self.folder_id = folder_id
        # URL unggahan (w.) didasarkan pada file direct_uploader.py
        self.api_url = "https://w.buzzheavier.com" 
        self.headers = {"Authorization": f"Bearer {self.token}"}

    async def upload_file(self, file_path: str, file_name: str = None):
        """Mengunggah satu file ke Buzzheavier menggunakan PUT."""
        if not file_name:
            file_name = os.path.basename(file_path)
        
        # URL encode nama file
        safe_file_name = quote(file_name)
        
        # Format URL unggahan
        upload_url = f"{self.api_url}/{self.folder_id}/{safe_file_name}"
        
        try:
            # Buka file dan stream-upload
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with open(file_path, 'rb') as f:
                    # Menggunakan PUT seperti yang diimplikasikan oleh logika pycurl
                    async with session.put(upload_url, data=f) as resp:
                        
                        result = await resp.json()
                        
                        # Periksa kode status dari respons JSON
                        if result.get("code") == 400:
                            raise Exception(f"File {file_name} sudah ada di akun (Error 400).")
                        if result.get("code") != 201:
                            resp.raise_for_status() # Lemparkan error HTTP jika bukan 201
                            
                        data = result.get("data")
                        if not data:
                            raise Exception("Respons tidak valid dari Buzzheavier.")
                            
                        file_id = data.get("id")
                        # Buat link unduhan final
                        final_link = f"https://buzzheavier.com/{file_id}"
                        LOGGER.info(f"Buzzheavier: Berhasil mengunggah {file_name} -> {final_link}")
                        return final_link

        except aiohttp.ClientResponseError as e:
             # Tangani error HTTP
             LOGGER.error(f"Buzzheavier: Error HTTP saat mengunggah {file_name}: {e.status} - {e.message} - {await resp.text()}")
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
                await user_message.edit(f"Mengunggah ke Buzzheavier...\nLagu {i+1} dari {total}\n`{filename}`")
            except:
                pass # Abaikan jika edit gagal
        
        try:
            link = await uploader.upload_file(filepath, filename)
            links.append(link)
        except Exception as e:
            LOGGER.error(f"Buzzheavier: Gagal mengunggah batch file {filename}: {e}")
            links.append(f"Gagal: {filename} ({e})")
            
    return links
