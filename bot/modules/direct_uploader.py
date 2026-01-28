import os
import asyncio
import requests
from bot.logger import LOGGER

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        self.is_cancelled = False

    def _get_server_sync(self):
        """Mendapatkan server Gofile (Sync)"""
        try:
            url = "https://api.gofile.io/servers"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'ok' and data.get('data', {}).get('servers'):
                    return data['data']['servers'][0]['name']
        except Exception as e:
            LOGGER.warning(f"Gofile Get Server Error: {e}")
        return "store1"

    def _upload_sync(self, file_name, filepath, token, folder_id):
        """Proses Upload Sync (Akan dijalankan di Thread)"""
        try:
            # 1. Dapatkan Server
            server = self._get_server_sync()
            upload_url = f"https://{server}.gofile.io/uploadFile"
            
            # 2. Siapkan File & Data
            # 'requests' menangani nama file Unicode (Korea/Jepang/Spasi) lebih baik daripada aiohttp
            # untuk server yang tidak decode header RFC-5987 dengan benar.
            with open(filepath, 'rb') as f:
                files = {
                    'file': (file_name, f) 
                }
                data = {
                    'token': token
                }
                if folder_id:
                    data['folderId'] = folder_id
                
                # 3. Eksekusi Upload
                response = requests.post(upload_url, files=files, data=data, timeout=3600) # Timeout 1 jam jaga-jaga file besar
                
                if response.status_code != 200:
                    LOGGER.error(f"Gofile Upload Failed: HTTP {response.status_code} - {response.text}")
                    return None
                
                result = response.json()
                if result.get('status') == 'ok':
                    download_page = result['data']['downloadPage']
                    LOGGER.info(f"Gofile Upload Sukses: {download_page}")
                    return {'Gofile': download_page}
                else:
                    LOGGER.error(f"Gofile API Error: {result}")
                    return None

        except Exception as e:
            LOGGER.error(f"DirectUpload Sync Error: {e}")
            return None

    async def upload(self, file_name, size, upload_type):
        """
        Fungsi utama upload (Async Wrapper)
        """
        if upload_type not in ['gf', 'gofile']:
            return None

        token = self.user_dict.get("gofile", {}).get("api")
        if not token:
            LOGGER.error("DirectUpload: Token Gofile tidak ditemukan.")
            return None

        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath):
            return None
        
        folder_id = self.user_dict.get("gofile", {}).get("folder_id")

        LOGGER.info(f"Memulai upload Gofile (Requests/Thread): {file_name}")

        # --- JALANKAN DI EXECUTOR (Agar bot tidak hang/lag saat upload) ---
        loop = asyncio.get_running_loop()
        # Kita bungkus fungsi sync '_upload_sync' agar berjalan di thread terpisah
        return await loop.run_in_executor(None, self._upload_sync, file_name, filepath, token, folder_id)
