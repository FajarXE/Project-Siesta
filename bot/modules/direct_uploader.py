# [FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import requests
import json
import re
import shutil
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
        
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    # ============================
    # CORE: CURL EXECUTOR
    # ============================
    async def _run_curl_upload(self, cmd_args):
        temp_log = f"curl_log_{os.getpid()}.txt"
        try:
            final_cmd = cmd_args + ["--http1.1"] 
            
            with open(temp_log, "w") as outfile:
                process = await asyncio.create_subprocess_exec(
                    *final_cmd,
                    stdout=outfile,
                    stderr=outfile
                )
                await process.wait()

            output = ""
            if os.path.exists(temp_log):
                with open(temp_log, "r") as f:
                    output = f.read().strip()
                os.remove(temp_log)
                
            if process.returncode == 0:
                return output
            else:
                LOGGER.error(f"CURL Failed (Code {process.returncode}): {output[:500]}")
                return None
        except Exception as e:
            LOGGER.error(f"CURL Ex Error: {e}")
            if os.path.exists(temp_log): os.remove(temp_log)
            return None

    # ============================
    # GOFILE HANDLER
    # ============================
    def _get_gofile_server(self):
        try:
            r = self.session.get("https://api.gofile.io/servers", timeout=10)
            if r.status_code == 200:
                return r.json()['data']['servers'][0]['name']
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

    async def gofile_get_root(self, token):
        try:
            acc_id = await asyncio.to_thread(self._get_gofile_account, token)
            if acc_id:
                r = await asyncio.to_thread(self.session.get, f"https://api.gofile.io/accounts/{acc_id}?token={token}")
                data = r.json()['data']
                return data['rootFolder']
        except: pass
        return None

    async def gofile_create_folder_async(self, token, parent_id, name):
        return await asyncio.to_thread(self._gofile_create_folder, token, parent_id, name)

    async def _upload_gofile_curl(self, filepath, token, folder_id):
        server = await asyncio.to_thread(self._get_gofile_server)
        url = f"https://{server}.gofile.io/uploadFile"
        
        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "POST", url,
            "-H", "Connection: keep-alive", 
            "-F", f"token={token}",
            "-F", f"file=@{filepath}"
        ]
        if folder_id:
            cmd.extend(["-F", f"folderId={folder_id}"])
            
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                match = re.search(r'(\{.*\})', output)
                if match:
                    res = json.loads(match.group(1))
                    if res.get('status') == 'ok':
                        return res['data']['downloadPage']
            except: pass
        return None

    # ============================
    # BUZZHEAVIER HANDLER
    # ============================
    def _buzzheavier_get_root(self, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = self.session.get("https://buzzheavier.com/api/fs", headers=headers, timeout=10)
            if r.json().get('code') == 200: return r.json()['data']['id']
        except: pass
        return None
    
    def _buzzheavier_create_folder(self, token, parent_id, name):
        try:
            url = f"https://buzzheavier.com/api/fs/{parent_id}"
            headers = {"Authorization": f"Bearer {token}"}
            data = {"name": name, "parentId": parent_id}
            
            r = self.session.post(url, headers=headers, json=data, timeout=15)
            res = r.json()
            if res.get('code') == 200: return res['data']['id']
            elif res.get('code') == 409: # Conflict
                match = re.search(r"\((\d+)\)$", name)
                if match:
                    num = int(match.group(1)) + 1
                    new_name = re.sub(r"\(\d+\)$", f"({num})", name)
                else:
                    new_name = f"{name} (1)"
                return self._buzzheavier_create_folder(token, parent_id, new_name)
        except: pass
        return None

    # --- PUBLIC WRAPPERS BUZZHEAVIER ---
    async def buzzheavier_get_root(self, token):
         return await asyncio.to_thread(self._buzzheavier_get_root, token)

    async def buzzheavier_create_folder_async(self, token, parent_id, name):
         return await asyncio.to_thread(self._buzzheavier_create_folder, token, parent_id, name)
    # -----------------------------------

    async def _upload_buzzheavier_curl(self, filepath, token, folder_id=None):
        filename = os.path.basename(filepath)
        url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}" if folder_id else f"https://w.buzzheavier.com/{quote(filename)}"
        
        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "PUT",
            "-H", f"Authorization: Bearer {token}",
            "-T", filepath,
            url
        ]
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                match = re.search(r'(\{.*\})', output)
                if match:
                    res = json.loads(match.group(1))
                    if res.get('code') == 201:
                        return f"https://buzzheavier.com/{res['data']['id']}"
            except: pass
        return None

    # ============================
    # VIKINGFILES HANDLER
    # ============================
    async def _upload_viking_curl(self, filepath, token):
        def get_srv():
            try: return self.session.get("https://vikingfile.com/api/get-server", timeout=10).json()['server']
            except: return None
        srv = await asyncio.to_thread(get_srv)
        if not srv: return None

        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "POST", srv,
            "-F", f"user={token}",
            "-F", f"file=@{filepath}"
        ]
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                match = re.search(r'(\{.*\})', output)
                if match:
                    res = json.loads(match.group(1))
                    if res.get('url'): return res['url']
            except: pass
        return None

    # ============================
    # PUBLIC METHODS
    # ============================
    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath): return None
        
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            fid = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            if token:
                LOGGER.info(f"Uploading Gofile (CURL): {file_name}")
                link = await self._upload_gofile_curl(filepath, token, fid)
                return {'Gofile': link} if link else None

        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Buzzheavier (CURL): {file_name}")
                # FIX: Pass specific_folder_id ke Buzzheavier CURL
                link = await self._upload_buzzheavier_curl(filepath, token, folder_id=specific_folder_id)
                return {'Buzzheavier': link} if link else None

        elif upload_type in ['vk', 'viking']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Viking (CURL): {file_name}")
                link = await self._upload_viking_curl(filepath, token)
                return {'Vikingfiles': link} if link else None

        return None
