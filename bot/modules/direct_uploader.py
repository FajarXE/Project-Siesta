import os
import aiohttp
import asyncio
from bot.logger import LOGGER

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        self.is_cancelled = False

    async def get_gofile_server(self, session, token):
        """Mendapatkan server upload terbaik dari Gofile"""
        try:
            # Menggunakan endpoint untuk mendapatkan server terbaik
            # Docs: https://gofile.io/api
            url = "https://api.gofile.io/servers"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get('status') == 'ok' and data.get('data', {}).get('servers'):
                        # Ambil server pertama yang tersedia
                        server = data['data']['servers'][0]['name']
                        return server
        except Exception as e:
            LOGGER.error(f"Gofile Get Server Error: {e}")
        
        # Fallback jika gagal (biasanya store1, store2, dll)
        return "store1"

    async def upload(self, file_name, size, upload_type):
        """
        Fungsi utama upload.
        upload_type: 'gf' atau 'gofile'
        """
        if upload_type not in ['gf', 'gofile']:
            return None

        # Ambil token dari listener (yang dipassing dari uploder.py)
        token = self.user_dict.get("gofile", {}).get("api")
        if not token:
            LOGGER.error("DirectUpload: Token Gofile tidak ditemukan.")
            return None

        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath):
            LOGGER.error(f"DirectUpload: File tidak ditemukan {filepath}")
            return None

        LOGGER.info(f"Memulai upload Gofile (AIOHTTP): {file_name}")

        async with aiohttp.ClientSession() as session:
            try:
                # 1. Dapatkan Server
                server = await self.get_gofile_server(session, token)
                upload_url = f"https://{server}.gofile.io/uploadFile"

                # 2. Siapkan Form Data
                data = aiohttp.FormData()
                # Field wajib untuk Gofile
                data.add_field('token', token)
                
                # Cek apakah ada folder_id (opsional)
                folder_id = self.user_dict.get("gofile", {}).get("folder_id")
                if folder_id:
                    data.add_field('folderId', folder_id)

                # Stream file upload agar hemat RAM
                f = open(filepath, 'rb')
                data.add_field('file', f, filename=file_name)

                # 3. Eksekusi Upload
                async with session.post(upload_url, data=data) as resp:
                    f.close() # Tutup file
                    
                    if resp.status != 200:
                        LOGGER.error(f"Gofile Upload Failed: HTTP {resp.status}")
                        return None
                    
                    result = await resp.json()
                    
                    if result.get('status') == 'ok':
                        # Gofile mengembalikan link downloadPage
                        download_page = result['data']['downloadPage']
                        LOGGER.info(f"Gofile Upload Sukses: {download_page}")
                        
                        # Return format sesuai yang diharapkan uploder.py
                        return {'Gofile': download_page}
                    else:
                        LOGGER.error(f"Gofile API Error: {result}")
                        return None

            except Exception as e:
                LOGGER.error(f"DirectUpload Exception: {e}")
                return None
