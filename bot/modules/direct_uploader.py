# [FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import requests
import json
from urllib.parse import quote
from bot.logger import LOGGER

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        self.is_cancelled = False

    # ============================
    # GOFILE HANDLER
    # ============================
    def _get_gofile_server(self):
        try:
            resp = requests.get("https://api.gofile.io/servers", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'ok' and data['data'].get('servers'):
                    return data['data']['servers'][0]['name']
        except: pass
        return "store1"

    def _get_gofile_account(self, token):
        try:
            r = requests.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=10)
            if r.status_code == 200 and r.json()['status'] == 'ok':
                return r.json()['data']['id']
        except: pass
        return None

    def _gofile_create_folder(self, token, parent_id, name):
        try:
            data = {'token': token, 'parentFolderId': parent_id, 'folderName': name}
            r = requests.post("https://api.gofile.io/contents/createFolder", data=data, timeout=10)
            if r.status_code == 200 and r.json()['status'] == 'ok':
                return r.json()['data']
        except Exception as e:
            LOGGER.error(f"Gofile Create Folder Error: {e}")
        return None

    def _upload_gofile(self, filepath, token, folder_id):
        server = self._get_gofile_server()
        url = f"https://{server}.gofile.io/uploadFile"
        try:
            with open(filepath, 'rb') as f:
                files = {'file': (os.path.basename(filepath), f)}
                data = {'token': token}
                if folder_id: data['folderId'] = folder_id
                
                r = requests.post(url, files=files, data=data, timeout=3600)
                res = r.json()
                if res.get('status') == 'ok':
                    return res['data']['downloadPage']
                else:
                    LOGGER.error(f"Gofile API Error: {res}")
        except Exception as e:
            LOGGER.error(f"Gofile Upload Error: {e}")
        return None

    # ============================
    # PIXELDRAIN HANDLER
    # ============================
    def _upload_pixeldrain(self, filepath, token):
        url = "https://pixeldrain.com/api/file"
        try:
            # Pixeldrain menggunakan Basic Auth (user='', password=token)
            auth = ('', token)
            filename = os.path.basename(filepath)
            
            with open(filepath, 'rb') as f:
                files = {'file': (filename, f)}
                data = {'name': filename, 'anonymous': 'false'}
                
                r = requests.post(url, auth=auth, files=files, data=data, timeout=3600)
                
                if r.status_code in [200, 201]:
                    res = r.json()
                    if res.get('success'):
                        return f"https://pixeldrain.com/u/{res['id']}"
                LOGGER.error(f"Pixeldrain Error: {r.text}")
        except Exception as e:
            LOGGER.error(f"Pixeldrain Upload Error: {e}")
        return None

    # ============================
    # BUZZHEAVIER HANDLER
    # ============================
    def _get_buzz_root(self, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get("https://buzzheavier.com/api/fs", headers=headers, timeout=10)
            res = r.json()
            if res.get('code') == 200:
                return res['data']['id']
        except: pass
        return None

    def _upload_buzzheavier(self, filepath, token):
        try:
            # Simple Upload (Tanpa Folder Support dulu untuk kestabilan)
            filename = os.path.basename(filepath)
            url = f"https://w.buzzheavier.com/{quote(filename)}"
            headers = {"Authorization": f"Bearer {token}"}
            
            with open(filepath, 'rb') as f:
                # Buzzheavier menggunakan PUT dengan body raw
                r = requests.put(url, headers=headers, data=f, timeout=3600)
                res = r.json()
                
                if res.get('code') == 201 and res.get('data'):
                    return f"https://buzzheavier.com/{res['data']['id']}"
                LOGGER.error(f"Buzzheavier Error: {res}")
        except Exception as e:
            LOGGER.error(f"Buzzheavier Upload Error: {e}")
        return None

    # ============================
    # VIKINGFILES HANDLER
    # ============================
    def _upload_viking(self, filepath, token):
        try:
            # 1. Get Server
            r_srv = requests.get("https://vikingfile.com/api/get-server", timeout=10)
            server_url = r_srv.json().get('server')
            
            if not server_url:
                raise Exception("No Viking server available")

            # 2. Upload
            filename = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                files = {'file': (filename, f)}
                data = {'user': token} # Token dikirim sebagai field 'user'
                
                r = requests.post(server_url, files=files, data=data, timeout=3600)
                res = r.json()
                
                if res.get('status') == 200 and res.get('url'):
                    return res['url']
                LOGGER.error(f"Vikingfiles Error: {res}")
        except Exception as e:
            LOGGER.error(f"Vikingfiles Upload Error: {e}")
        return None


    # ============================
    # PUBLIC METHODS
    # ============================
    
    # Helper async untuk membuat folder Gofile
    async def gofile_create_folder_async(self, token, parent_id, name):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._gofile_create_folder, token, parent_id, name)

    async def gofile_get_root(self, token):
        loop = asyncio.get_running_loop()
        # Ambil Account ID dulu lalu Root Folder
        try:
            acc_id = await loop.run_in_executor(None, self._get_gofile_account, token)
            if acc_id:
                # Logic sederhana: request ulang ke endpoint akun untuk dapat rootFolder
                # (Disederhanakan di sini, implementasi penuh ada di _get_gofile_account jika API mengembalikan data lengkap)
                # API Gofile getAccount biasanya mengembalikan rootFolder
                r = await loop.run_in_executor(None, requests.get, f"https://api.gofile.io/accounts/{acc_id}?token={token}")
                data = r.json()['data']
                return data['rootFolder']
        except: pass
        return None

    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        """
        Main Upload Entrypoint.
        upload_type: 'gofile', 'pixeldrain', 'buzzheavier', 'viking'
        """
        loop = asyncio.get_running_loop()
        filepath = os.path.join(self.path, file_name)
        
        if not os.path.exists(filepath):
            return None

        # 1. GOFILE
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            if not token: return None
            # Gunakan folder ID spesifik jika disediakan (untuk album), jika tidak pakai default
            folder_target = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            
            LOGGER.info(f"Uploading Gofile: {file_name}")
            link = await loop.run_in_executor(None, self._upload_gofile, filepath, token, folder_target)
            return {'Gofile': link} if link else None

        # 2. PIXELDRAIN
        elif upload_type in ['pd', 'pixeldrain']:
            token = self.user_dict.get("pixeldrain", {}).get("api")
            if not token: return None
            
            LOGGER.info(f"Uploading Pixeldrain: {file_name}")
            link = await loop.run_in_executor(None, self._upload_pixeldrain, filepath, token)
            return {'Pixeldrain': link} if link else None

        # 3. BUZZHEAVIER
        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if not token: return None
            
            LOGGER.info(f"Uploading Buzzheavier: {file_name}")
            link = await loop.run_in_executor(None, self._upload_buzzheavier, filepath, token)
            return {'Buzzheavier': link} if link else None

        # 4. VIKINGFILES
        elif upload_type in ['vk', 'viking', 'vikingfiles']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if not token: return None
            
            LOGGER.info(f"Uploading Vikingfiles: {file_name}")
            link = await loop.run_in_executor(None, self._upload_viking, filepath, token)
            return {'Vikingfiles': link} if link else None

        return None
