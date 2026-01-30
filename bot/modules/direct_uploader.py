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
        
        # Session hanya untuk metadata ringan
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    # ============================
    # CORE: CURL EXECUTOR (ANTI-STUCK VERSION)
    # ============================
    async def _run_curl_upload(self, cmd_args):
        """
        Menjalankan CURL tanpa PIPE blocking untuk mencegah stuck di file besar.
        Output disimpan ke file temporary lalu dibaca.
        """
        temp_log = f"curl_log_{os.getpid()}.txt"
        
        try:
            # Buka file log fisik, bukan PIPE memory
            with open(temp_log, "w") as outfile:
                process = await asyncio.create_subprocess_exec(
                    *cmd_args,
                    stdout=outfile, # Tulis langsung ke disk
                    stderr=outfile  # Tulis langsung ke disk
                )
                await process.wait() # Tunggu sampai selesai

            # Baca hasilnya setelah selesai
            if os.path.exists(temp_log):
                with open(temp_log, "r") as f:
                    output = f.read().strip()
                os.remove(temp_log) # Bersihkan
                
                # Cek sukses
                if process.returncode == 0:
                    return output
                else:
                    LOGGER.error(f"CURL Failed (Code {process.returncode}): {output}")
                    return None
            return None

        except Exception as e:
            LOGGER.error(f"CURL Execution Error: {e}")
            if os.path.exists(temp_log): os.remove(temp_log)
            return None

    # ============================
    # GOFILE HANDLER
    # ============================
    def _get_gofile_server(self):
        try:
            r = self.session.get("https://api.gofile.io/servers", timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get('status') == 'ok' and data['data'].get('servers'):
                    return data['data']['servers'][0]['name']
        except: pass
        return "store1"

    async def _upload_gofile_curl(self, filepath, token, folder_id):
        server = await asyncio.to_thread(self._get_gofile_server)
        url = f"https://{server}.gofile.io/uploadFile"
        
        # Tambahkan --no-buffer dan timeout setting
        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "POST", url,
            "-F", f"token={token}",
            "-F", f"file=@{filepath}"
        ]
        if folder_id:
            cmd.extend(["-F", f"folderId={folder_id}"])
            
        output = await self._run_curl_upload(cmd)
        if output:
            # Gofile kadang mengembalikan JSON di baris terakhir output curl
            # Kita cari kurung kurawal json
            try:
                # Regex untuk menangkap JSON valid dari output yang mungkin kotor
                match = re.search(r'(\{.*\})', output)
                if match:
                    res = json.loads(match.group(1))
                    if res.get('status') == 'ok':
                        return res['data']['downloadPage']
            except:
                LOGGER.error(f"Gofile Parse Error. Raw: {output[:200]}")
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

    async def _upload_buzzheavier_curl(self, filepath, token, folder_id=None):
        filename = os.path.basename(filepath)
        url_base = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}" if folder_id else f"https://w.buzzheavier.com/{quote(filename)}"
        
        # Buzzheavier PUT upload
        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "PUT",
            "-H", f"Authorization: Bearer {token}",
            "-T", filepath,
            url_base
        ]
        
        output = await self._run_curl_upload(cmd)
        if output:
            try:
                match = re.search(r'(\{.*\})', output)
                if match:
                    res = json.loads(match.group(1))
                    if res.get('code') == 201:
                        return f"https://buzzheavier.com/{res['data']['id']}"
            except:
                LOGGER.error(f"Buzzheavier Parse Error. Raw: {output[:200]}")
        return None

    # ============================
    # VIKINGFILES HANDLER
    # ============================
    async def _upload_viking_curl(self, filepath, token):
        # Ambil server via requests (ringan)
        def get_srv():
            try: return self.session.get("https://vikingfile.com/api/get-server", timeout=10).json()['server']
            except: return None
        
        server_url = await asyncio.to_thread(get_srv)
        if not server_url: return None

        cmd = [
            "curl", "-s", "--no-buffer",
            "-X", "POST", server_url,
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
    # PUBLIC METHODS (SAMA)
    # ============================
    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath) or os.path.isdir(filepath): return None

        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            fid = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            if token:
                LOGGER.info(f"Uploading Gofile (CURL-File): {file_name}")
                link = await self._upload_gofile_curl(filepath, token, fid)
                return {'Gofile': link} if link else None

        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Buzzheavier (CURL-File): {file_name}")
                link = await self._upload_buzzheavier_curl(filepath, token)
                return {'Buzzheavier': link} if link else None

        elif upload_type in ['vk', 'viking']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Viking (CURL-File): {file_name}")
                link = await self._upload_viking_curl(filepath, token)
                return {'Vikingfiles': link} if link else None

        return None
