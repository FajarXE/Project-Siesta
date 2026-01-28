# [FILE: bot/modules/direct_uploader.py]

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

    def _get_account_root(self, token):
        """Mendapatkan Root Folder ID dari akun user"""
        try:
            # 1. Get Account ID
            r1 = requests.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=10)
            if r1.status_code == 200 and r1.json()['status'] == 'ok':
                acc_id = r1.json()['data']['id']
                
                # 2. Get Account Details (Root Folder)
                r2 = requests.get(f"https://api.gofile.io/accounts/{acc_id}?token={token}", timeout=10)
                if r2.status_code == 200 and r2.json()['status'] == 'ok':
                    return r2.json()['data']['rootFolder']
        except Exception as e:
            LOGGER.error(f"Gofile Get Account Error: {e}")
        return None

    def _create_folder_sync(self, token, parent_id, name):
        """Membuat Folder Baru di Gofile"""
        try:
            url = "https://api.gofile.io/contents/createFolder"
            # API Gofile meminta token, parentFolderId, dan folderName
            data = {
                'token': token,
                'parentFolderId': parent_id,
                'folderName': name
            }
            resp = requests.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                res = resp.json()
                if res['status'] == 'ok':
                    # Mengembalikan ID folder baru dan CODE (untuk link)
                    return res['data'] # {'id': '...', 'code': '...', ...}
        except Exception as e:
            LOGGER.error(f"Gofile Create Folder Error: {e}")
        return None

    def _upload_sync(self, file_name, filepath, token, folder_id):
        """Proses Upload Sync"""
        try:
            server = self._get_server_sync()
            upload_url = f"https://{server}.gofile.io/uploadFile"
            
            with open(filepath, 'rb') as f:
                files = {'file': (file_name, f)}
                data = {'token': token}
                if folder_id:
                    data['folderId'] = folder_id
                
                response = requests.post(upload_url, files=files, data=data, timeout=3600)
                
                if response.status_code != 200:
                    LOGGER.error(f"Gofile Upload Failed: HTTP {response.status_code}")
                    return None
                
                result = response.json()
                if result.get('status') == 'ok':
                    return {'Gofile': result['data']['downloadPage']}
                else:
                    LOGGER.error(f"Gofile API Error: {result}")
                    return None

        except Exception as e:
            LOGGER.error(f"DirectUpload Sync Error: {e}")
            return None

    # --- HELPER METHOD UNTUK AKSES DARI UPLODER.PY ---
    async def create_folder(self, token, parent_id, name):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._create_folder_sync, token, parent_id, name)
    
    async def get_root_folder(self, token):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_account_root, token)

    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        if upload_type not in ['gf', 'gofile']:
            return None

        token = self.user_dict.get("gofile", {}).get("api")
        if not token:
            return None

        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath):
            return None
        
        # Prioritaskan specific_folder_id jika ada (untuk upload ke dalam folder album)
        folder_id = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")

        LOGGER.info(f"Uploading Gofile: {file_name} -> FolderID: {folder_id}")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._upload_sync, file_name, filepath, token, folder_id)
