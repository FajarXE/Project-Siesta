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
        
        # Session Setup (Hanya untuk Metadata/API kecil)
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "PUT", "POST", "OPTIONS"]
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    # ============================
    # CORE: CURL EXECUTOR (THE SOLVER)
    # ============================
    async def _run_curl_upload(self, cmd_args):
        """Menjalankan CURL via Subprocess agar bypass limit 2GB Python"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                err_msg = stderr.decode().strip()
                LOGGER.error(f"CURL Failed: {err_msg}")
                return None
            
            return stdout.decode().strip()
        except Exception as e:
            LOGGER.error(f"CURL Exception: {e}")
            return None

    # ============================
    # GOFILE HANDLER
    # ============================
    def _get_gofile_server(self):
        try:
            resp = self.session.get("https://api.gofile.io/servers", timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'ok' and data['data'].get('servers'):
                    return data['data']['servers'][0]['name']
        except: pass
        return "store1"

    def _get_gofile_account(self, token):
        try:
            r = self.session.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=15)
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

    async def _upload_gofile_curl(self, filepath, token, folder_id):
        server = await asyncio.to_thread(self._get_gofile_server)
        url = f"https://{server}.gofile.io/uploadFile"
        
        # Susun Command CURL
        # -F untuk form-data, @ untuk file
        cmd = [
            "curl", "-s", 
            "-X", "POST", url,
            "-F", f"token={token}",
            "-F", f"file=@{filepath}"
        ]
        
        if folder_id:
            cmd.extend(["-F", f"folderId={folder_id}"])
            
        # Eksekusi
        output = await self._run_curl_upload(cmd)
        
        if output:
            try:
                res = json.loads(output)
                if res.get('status') == 'ok':
                    return res['data']['downloadPage']
                else:
                    LOGGER.error(f"Gofile API Error (CURL): {res}")
            except json.JSONDecodeError:
                LOGGER.error(f"Gofile Response Parse Error: {output}")
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
            
            if res.get('code') == 200:
                return res['data']['id']
            elif res.get('code') == 409:
                # Conflict logic (sama seperti sebelumnya)
                match = re.search(r"\((\d+)\)$", name)
                if match:
                    num = int(match.group(1)) + 1
                    new_name = re.sub(r"\(\d+\)$", f"({num})", name)
                else:
                    new_name = f"{name} (1)"
                return self._buzzheavier_create_folder(token, parent_id, new_name)
        except Exception as e:
            LOGGER.error(f"Buzzheavier Create Folder Error: {e}")
        return None

    async def _upload_buzzheavier_curl(self, filepath, token, folder_id=None):
        filename = os.path.basename(filepath)
        if folder_id:
            url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}"
        else:
            url = f"https://w.buzzheavier.com/{quote(filename)}"
            
        # Buzzheavier pakai PUT binary body
        # curl -T filepath -H "Authorization..." url
        cmd = [
            "curl", "-s",
            "-X", "PUT",
            "-H", f"Authorization: Bearer {token}",
            "-T", filepath,
            url
        ]
        
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                res = json.loads(output)
                if res.get('code') == 201 and res.get('data'):
                    return f"https://buzzheavier.com/{res['data']['id']}"
                LOGGER.error(f"Buzzheavier Error (CURL): {res}")
            except:
                LOGGER.error(f"Buzzheavier Parse Error: {output}")
        return None

    async def _upload_buzzheavier_folder_recursive(self, folderpath, token):
        # Logic folder structure tetap pakai requests (cepat & kecil)
        root_id = await asyncio.to_thread(self._buzzheavier_get_root, token)
        if not root_id: return None
        
        folder_name = os.path.basename(folderpath)
        created_folder_id = await asyncio.to_thread(self._buzzheavier_create_folder, token, root_id, folder_name)
        if not created_folder_id: return None
        
        # Loop file upload pakai CURL
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                full_path = os.path.join(root, file)
                # Panggil upload file curl secara langsung
                await self._upload_buzzheavier_curl(full_path, token, folder_id=created_folder_id)
        
        return f"https://buzzheavier.com/{created_folder_id}"

    # ============================
    # VIKINGFILES HANDLER
    # ============================
    async def _upload_viking_curl(self, filepath, token):
        if os.path.isdir(filepath): return None

        # 1. Get Server (Tetap requests)
        def get_server():
            try:
                r = self.session.get("https://vikingfile.com/api/get-server", timeout=15)
                return r.json().get('server')
            except: return None
            
        server_url = await asyncio.to_thread(get_server)
        if not server_url: 
            LOGGER.error("No Viking server found")
            return None

        # 2. Upload via CURL
        # Viking butuh field 'user' dan 'file'
        cmd = [
            "curl", "-s",
            "-X", "POST", server_url,
            "-F", f"user={token}",
            "-F", f"file=@{filepath}"
        ]
        
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                res = json.loads(output)
                if res.get('url'): return res['url']
                LOGGER.error(f"Viking Error (CURL): {res}")
            except:
                LOGGER.error(f"Viking Parse Error: {output}")
        return None

    # ============================
    # PUBLIC METHODS
    # ============================
    async def gofile_create_folder_async(self, token, parent_id, name):
        return await asyncio.to_thread(self._gofile_create_folder, token, parent_id, name)

    async def gofile_get_root(self, token):
        try:
            acc_id = await asyncio.to_thread(self._get_gofile_account, token)
            if acc_id:
                r = await asyncio.to_thread(self.session.get, f"https://api.gofile.io/accounts/{acc_id}?token={token}")
                data = r.json()['data']
                return data['rootFolder']
        except: pass
        return None

    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        # Tidak perlu loop.run_in_executor lagi karena method internal sudah async (subprocess)
        filepath = os.path.join(self.path, file_name)
        
        if not os.path.exists(filepath): return None
        is_directory = os.path.isdir(filepath)

        # 1. GOFILE
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            if not token: return None
            
            folder_target = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            LOGGER.info(f"Uploading Gofile (CURL): {file_name}")
            
            link = await self._upload_gofile_curl(filepath, token, folder_target)
            return {'Gofile': link} if link else None

        # 2. BUZZHEAVIER
        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if not token: return None
            
            if is_directory:
                LOGGER.info(f"Uploading Buzzheavier Folder (CURL): {file_name}")
                link = await self._upload_buzzheavier_folder_recursive(filepath, token)
            else:
                LOGGER.info(f"Uploading Buzzheavier File (CURL): {file_name}")
                link = await self._upload_buzzheavier_curl(filepath, token)
            
            return {'Buzzheavier': link} if link else None

        # 3. VIKINGFILES
        elif upload_type in ['vk', 'viking', 'vikingfiles']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if not token: return None
            
            if is_directory:
                LOGGER.error(f"Vikingfiles skipping folder: {file_name}")
                return None
            
            LOGGER.info(f"Uploading Vikingfiles (CURL): {file_name}")
            link = await self._upload_viking_curl(filepath, token)
            return {'Vikingfiles': link} if link else None

        return None
