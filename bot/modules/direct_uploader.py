# [FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import requests
import json
import re
from urllib.parse import quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bot.logger import LOGGER

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        self.is_cancelled = False
        
        # Session Setup
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "POST", "OPTIONS"]
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    # ============================
    # GOFILE HANDLER
    # ============================
    def _get_gofile_server(self):
        try:
            resp = self.session.get("https://api.gofile.io/servers", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'ok' and data['data'].get('servers'):
                    return data['data']['servers'][0]['name']
        except: pass
        return "store1"

    def _get_gofile_account(self, token):
        try:
            r = self.session.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=10)
            if r.status_code == 200 and r.json()['status'] == 'ok':
                return r.json()['data']['id']
        except: pass
        return None

    def _gofile_create_folder(self, token, parent_id, name):
        try:
            data = {'token': token, 'parentFolderId': parent_id, 'folderName': name}
            r = self.session.post("https://api.gofile.io/contents/createFolder", data=data, timeout=15)
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
                
                r = self.session.post(url, files=files, data=data, timeout=3600)
                res = r.json()
                if res.get('status') == 'ok':
                    return res['data']['downloadPage']
                else:
                    LOGGER.error(f"Gofile API Error: {res}")
        except Exception as e:
            LOGGER.error(f"Gofile Upload Error: {e}")
        return None

    # ============================
    # BUZZHEAVIER HANDLER
    # ============================
    def _buzzheavier_get_root(self, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = self.session.get("https://buzzheavier.com/api/fs", headers=headers, timeout=15)
            res = r.json()
            if res.get('code') == 200:
                return res['data']['id']
        except Exception as e:
            LOGGER.error(f"Buzzheavier Get Root Error: {e}")
        return None

    def _buzzheavier_create_folder(self, token, parent_id, name):
        try:
            url = f"https://buzzheavier.com/api/fs/{parent_id}"
            headers = {"Authorization": f"Bearer {token}"}
            data = {"name": name, "parentId": parent_id}
            
            r = self.session.post(url, headers=headers, json=data, timeout=15)
            res = r.json()
            
            # 200 OK
            if res.get('code') == 200:
                return res['data']['id']
            
            # 409 CONFLICT (Folder Exists) -> Auto Rename Logic
            elif res.get('code') == 409:
                LOGGER.warning(f"Buzzheavier folder '{name}' conflict. Renaming...")
                
                # Cek apakah nama sudah berakhiran (angka), misal: Folder (1)
                match = re.search(r"\((\d+)\)$", name)
                if match:
                    # Jika sudah ada angka, increment angkanya
                    num = int(match.group(1)) + 1
                    new_name = re.sub(r"\(\d+\)$", f"({num})", name)
                else:
                    # Jika belum ada, tambahkan (1)
                    new_name = f"{name} (1)"
                
                # Coba buat lagi dengan nama baru (Rekursif)
                return self._buzzheavier_create_folder(token, parent_id, new_name)
                
        except Exception as e:
            LOGGER.error(f"Buzzheavier Create Folder Error: {e}")
        return None

    def _upload_buzzheavier_file(self, filepath, token, folder_id=None):
        try:
            filename = os.path.basename(filepath)
            # Jika ada folder_id, URL berubah formatnya
            if folder_id:
                url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}"
            else:
                url = f"https://w.buzzheavier.com/{quote(filename)}"
            
            headers = {"Authorization": f"Bearer {token}"}
            
            # PENTING: Cek jika ini direktori (guard clause)
            if os.path.isdir(filepath):
                return None 
            
            with open(filepath, 'rb') as f:
                r = self.session.put(url, headers=headers, data=f, timeout=3600)
                res = r.json()
                if res.get('code') == 201 and res.get('data'):
                    # Jika upload ke folder, kita tidak butuh link per file, tapi sukses ID
                    return f"https://buzzheavier.com/{res['data']['id']}"
                LOGGER.error(f"Buzzheavier Error: {res}")
        except Exception as e:
            LOGGER.error(f"Buzzheavier Upload Error: {e}")
        return None

    def _upload_buzzheavier_folder_recursive(self, folderpath, token):
        try:
            # 1. Get Root
            root_id = self._buzzheavier_get_root(token)
            if not root_id: return None
            
            # 2. Create Parent Folder
            folder_name = os.path.basename(folderpath)
            created_folder_id = self._buzzheavier_create_folder(token, root_id, folder_name)
            if not created_folder_id: return None
            
            # 3. Walk and Upload
            for root, dirs, files in os.walk(folderpath):
                for file in files:
                    full_path = os.path.join(root, file)
                    self._upload_buzzheavier_file(full_path, token, folder_id=created_folder_id)
            
            return f"https://buzzheavier.com/{created_folder_id}"
        except Exception as e:
            LOGGER.error(f"Buzzheavier Recursive Error: {e}")
        return None

    # ============================
    # VIKINGFILES HANDLER
    # ============================
    def _upload_viking(self, filepath, token):
        try:
            if os.path.isdir(filepath):
                LOGGER.error("Vikingfiles does not support folder upload directly.")
                return None

            r_srv = self.session.get("https://vikingfile.com/api/get-server", timeout=15)
            server_url = r_srv.json().get('server')
            if not server_url: raise Exception("No Viking server available")

            filename = os.path.basename(filepath)
            with open(filepath, 'rb') as f:
                files = {'file': (filename, f)}
                data = {'user': token} 
                r = self.session.post(server_url, files=files, data=data, timeout=3600)
                res = r.json()
                if res.get('url'): return res['url']
                LOGGER.error(f"Vikingfiles Error: {res}")
        except Exception as e:
            LOGGER.error(f"Vikingfiles Upload Error: {e}")
        return None

    # ============================
    # PUBLIC METHODS
    # ============================
    async def gofile_create_folder_async(self, token, parent_id, name):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._gofile_create_folder, token, parent_id, name)

    async def gofile_get_root(self, token):
        loop = asyncio.get_running_loop()
        try:
            acc_id = await loop.run_in_executor(None, self._get_gofile_account, token)
            if acc_id:
                r = await loop.run_in_executor(None, self.session.get, f"https://api.gofile.io/accounts/{acc_id}?token={token}")
                data = r.json()['data']
                return data['rootFolder']
        except: pass
        return None

    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        loop = asyncio.get_running_loop()
        filepath = os.path.join(self.path, file_name)
        
        if not os.path.exists(filepath): return None
        is_directory = os.path.isdir(filepath)

        # 1. GOFILE
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            if not token: return None
            
            folder_target = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            LOGGER.info(f"Uploading Gofile: {file_name}")
            link = await loop.run_in_executor(None, self._upload_gofile, filepath, token, folder_target)
            return {'Gofile': link} if link else None

        # 2. BUZZHEAVIER
        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if not token: return None
            
            if is_directory:
                LOGGER.info(f"Uploading Buzzheavier Folder: {file_name}")
                link = await loop.run_in_executor(None, self._upload_buzzheavier_folder_recursive, filepath, token)
            else:
                LOGGER.info(f"Uploading Buzzheavier File: {file_name}")
                link = await loop.run_in_executor(None, self._upload_buzzheavier_file, filepath, token)
            
            return {'Buzzheavier': link} if link else None

        # 3. VIKINGFILES
        elif upload_type in ['vk', 'viking', 'vikingfiles']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if not token: return None
            
            if is_directory:
                LOGGER.error(f"Vikingfiles received a folder: {file_name}. Skipping.")
                return None
            
            LOGGER.info(f"Uploading Vikingfiles: {file_name}")
            link = await loop.run_in_executor(None, self._upload_viking, filepath, token)
            return {'Vikingfiles': link} if link else None

        return None
