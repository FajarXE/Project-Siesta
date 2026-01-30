# [FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import json
import re
from urllib.parse import quote
import aiohttp
import aiofiles
from bot.logger import LOGGER

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        self.is_cancelled = False
        
    # ============================
    # HELPER: AIOHTTP REQUEST
    # ============================
    async def _post_json(self, url, data=None, headers=None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=data, data=data if not isinstance(data, dict) else None, headers=headers) as resp:
                    return await resp.json()
            except Exception as e:
                LOGGER.error(f"Req Error: {e}")
                return None

    async def _get_json(self, url, headers=None):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers) as resp:
                    return await resp.json()
            except Exception as e:
                LOGGER.error(f"Req Error: {e}")
                return None

    # ============================
    # GOFILE HANDLER (AIOHTTP)
    # ============================
    async def _get_gofile_server(self):
        res = await self._get_json("https://api.gofile.io/servers")
        if res and res.get('status') == 'ok' and res['data'].get('servers'):
            return res['data']['servers'][0]['name']
        return "store1"

    async def _get_gofile_account(self, token):
        res = await self._get_json(f"https://api.gofile.io/accounts/getid?token={token}")
        if res and res.get('status') == 'ok':
            return res['data']['id']
        return None

    async def gofile_create_folder_async(self, token, parent_id, name):
        data = {'token': token, 'parentFolderId': parent_id, 'folderName': name}
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.gofile.io/contents/createFolder", data=data) as resp:
                res = await resp.json()
                if res.get('status') == 'ok':
                    return res['data']
        return None

    async def _upload_gofile(self, filepath, token, folder_id):
        server = await self._get_gofile_server()
        url = f"https://{server}.gofile.io/uploadFile"
        
        # AIOHTTP Multipart Streaming
        data = aiohttp.FormData()
        data.add_field('token', token)
        if folder_id:
            data.add_field('folderId', folder_id)
        
        # Open file stream
        # Menggunakan 'open' biasa aman di sini karena dibaca stream oleh aiohttp
        f = open(filepath, 'rb') 
        try:
            data.add_field('file', f, filename=os.path.basename(filepath), content_type='application/octet-stream')
            
            # Timeout None = Unlimited (Penting untuk file > 2GB)
            timeout = aiohttp.ClientTimeout(total=None)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=data) as resp:
                    res = await resp.json()
                    if res.get('status') == 'ok':
                        return res['data']['downloadPage']
                    else:
                        LOGGER.error(f"Gofile Error: {res}")
        except Exception as e:
            LOGGER.error(f"Gofile Upload Exception: {e}")
        finally:
            f.close()
        return None

    # ============================
    # BUZZHEAVIER HANDLER (AIOHTTP)
    # ============================
    async def _buzzheavier_get_root(self, token):
        headers = {"Authorization": f"Bearer {token}"}
        res = await self._get_json("https://buzzheavier.com/api/fs", headers=headers)
        if res and res.get('code') == 200:
            return res['data']['id']
        return None

    async def _buzzheavier_create_folder(self, token, parent_id, name):
        url = f"https://buzzheavier.com/api/fs/{parent_id}"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"name": name, "parentId": parent_id}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                res = await resp.json()
                if res.get('code') == 200:
                    return res['data']['id']
                elif res.get('code') == 409:
                    LOGGER.warning(f"Buzzheavier conflict {name}. Renaming...")
                    return await self._buzzheavier_create_folder(token, parent_id, name + " (1)")
        return None

    async def _upload_buzzheavier_file(self, filepath, token, folder_id=None):
        filename = os.path.basename(filepath)
        url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}" if folder_id else f"https://w.buzzheavier.com/{quote(filename)}"
        headers = {"Authorization": f"Bearer {token}"}

        if os.path.isdir(filepath): return None
        
        f = open(filepath, 'rb')
        try:
            timeout = aiohttp.ClientTimeout(total=None)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Buzzheavier menggunakan PUT binary body
                async with session.put(url, headers=headers, data=f) as resp:
                    res = await resp.json()
                    if res.get('code') == 201:
                        return f"https://buzzheavier.com/{res['data']['id']}"
                    LOGGER.error(f"Buzzheavier Error: {res}")
        except Exception as e:
            LOGGER.error(f"Buzzheavier Upload Exception: {e}")
        finally:
            f.close()
        return None

    async def _upload_buzzheavier_folder_recursive(self, folderpath, token):
        root_id = await self._buzzheavier_get_root(token)
        if not root_id: return None
        
        folder_name = os.path.basename(folderpath)
        created_folder_id = await self._buzzheavier_create_folder(token, root_id, folder_name)
        if not created_folder_id: return None
        
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                full_path = os.path.join(root, file)
                await self._upload_buzzheavier_file(full_path, token, folder_id=created_folder_id)
        
        return f"https://buzzheavier.com/{created_folder_id}"

    # ============================
    # VIKINGFILES HANDLER (AIOHTTP)
    # ============================
    async def _upload_viking(self, filepath, token):
        if os.path.isdir(filepath): return None

        # 1. Get Server
        res = await self._get_json("https://vikingfile.com/api/get-server")
        server_url = res.get('server') if res else None
        if not server_url: return None

        # 2. Upload Multipart
        data = aiohttp.FormData()
        data.add_field('user', token)
        
        f = open(filepath, 'rb')
        try:
            data.add_field('file', f, filename=os.path.basename(filepath), content_type='application/octet-stream')
            
            timeout = aiohttp.ClientTimeout(total=None)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(server_url, data=data) as resp:
                    res = await resp.json()
                    if res.get('url'): return res['url']
                    LOGGER.error(f"Viking Error: {res}")
        except Exception as e:
            LOGGER.error(f"Viking Exception: {e}")
        finally:
            f.close()
        return None

    # ============================
    # PUBLIC METHODS
    # ============================
    async def gofile_get_root(self, token):
        acc_id = await self._get_gofile_account(token)
        if acc_id:
            res = await self._get_json(f"https://api.gofile.io/accounts/{acc_id}?token={token}")
            if res: return res['data']['rootFolder']
        return None

    async def upload(self, file_name, size, upload_type, specific_folder_id=None):
        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath): return None
        is_directory = os.path.isdir(filepath)

        # 1. GOFILE
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            folder_target = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            if token:
                LOGGER.info(f"Uploading Gofile (AIOHTTP): {file_name}")
                link = await self._upload_gofile(filepath, token, folder_target)
                return {'Gofile': link} if link else None

        # 2. BUZZHEAVIER
        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if token:
                if is_directory:
                    LOGGER.info(f"Uploading Buzzheavier Folder (AIOHTTP): {file_name}")
                    link = await self._upload_buzzheavier_folder_recursive(filepath, token)
                else:
                    LOGGER.info(f"Uploading Buzzheavier File (AIOHTTP): {file_name}")
                    link = await self._upload_buzzheavier_file(filepath, token)
                return {'Buzzheavier': link} if link else None

        # 3. VIKINGFILES
        elif upload_type in ['vk', 'viking', 'vikingfiles']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if token and not is_directory:
                LOGGER.info(f"Uploading Vikingfiles (AIOHTTP): {file_name}")
                link = await self._upload_viking(filepath, token)
                return {'Vikingfiles': link} if link else None

        return None
