# [FILE: bot/helpers/uploder.py]

import os
import asyncio
import shutil
from config import Config 
from pyrogram.errors import MessageNotModified

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *
from bot.logger import LOGGER 

from ..modules.direct_uploader import DirectUpload

class FakeListener:
    def __init__(self, user_dict):
        self.user_dict = user_dict
        self.extra_details = {} 
        self.is_cancelled = False 
    async def onUploadError(self, error):
        LOGGER.error(f"Cloud Upload Error: {error}")
        return str(error)

async def upload_to_cloud_handler(filepath, user, metadata, mode):
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    
    if mode == 'Gofile': token = user_data.get('gofile_token')
    elif mode == 'Buzzheavier': token = user_data.get('buzzheavier_token')
    elif mode == 'Vikingfiles': token = user_data.get('viking_token')
    
    if not token:
        await send_message(user, f"⚠️ <b>{mode} Token Missing!</b>", 'text')
        return None

    server_dict = {
        "gofile": {"api": user_data.get('gofile_token')},
        "buzzheavier": {"api": user_data.get('buzzheavier_token')},
        "vikingfiles": {"api": user_data.get('viking_token')}
    }
    
    # Penanganan path aman (List atau String)
    if isinstance(filepath, list):
         base_path = os.path.dirname(filepath[0])
    elif os.path.isfile(filepath):
         base_path = os.path.dirname(filepath)
    else:
         base_path = os.path.dirname(filepath.rstrip('/'))

    listener = FakeListener(server_dict)
    uploader = DirectUpload(listener=listener, path=base_path)

    try:
        folder_name = metadata.get('title', 'Unknown Album')

        # === KASUS 1: SPLIT FILES (LIST) ===
        if isinstance(filepath, list):
            if 'bot_msg' in user: 
                await edit_message(user['bot_msg'], f"📂 Uploading {len(filepath)} parts to {mode}...")

            # A. GOFILE (Folder)
            if mode == 'Gofile':
                root_id = await uploader.gofile_get_root(token)
                new_folder = await uploader.gofile_create_folder_async(token, root_id, folder_name)
                if new_folder:
                    for idx, part in enumerate(filepath, 1):
                        await edit_message(user['bot_msg'], f"🚀 {mode}: Uploading Part {idx}/{len(filepath)}...")
                        await uploader.upload(os.path.basename(part), 0, 'gofile', specific_folder_id=new_folder['id'])
                    return f"https://gofile.io/d/{new_folder['code']}"

            # B. BUZZHEAVIER (Folder)
            elif mode == 'Buzzheavier':
                root_id = await uploader.buzzheavier_get_root(token)
                parent_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
                if parent_id:
                    for idx, part in enumerate(filepath, 1):
                        await edit_message(user['bot_msg'], f"🚀 {mode}: Uploading Part {idx}/{len(filepath)}...")
                        await uploader.upload(os.path.basename(part), 0, 'buzzheavier', specific_folder_id=parent_id)
                    return f"https://buzzheavier.com/{parent_id}"
                
            # C. VIKINGFILES (List Links - No Folder)
            elif mode == 'Vikingfiles':
                links = []
                for idx, part in enumerate(filepath, 1):
                    await edit_message(user['bot_msg'], f"🚀 {mode}: Uploading Part {idx}/{len(filepath)}...")
                    res = await uploader.upload(os.path.basename(part), 0, 'viking')
                    if res: links.append(list(res.values())[0])
                return "\n".join(links)

        # === KASUS 2: SINGLE FILE (ZIP) ===
        elif os.path.isfile(filepath):
            if 'bot_msg' in user: await edit_message(user['bot_msg'], f"🚀 Uploading to {mode}...")
            
            # Buzzheavier: Buat folder dulu biar rapi
            if mode == 'Buzzheavier': 
                root_id = await uploader.buzzheavier_get_root(token)
                parent_id = await uploader.buzzheavier_create_folder_async(token, root_id, folder_name)
                res = await uploader.upload(os.path.basename(filepath), 0, 'buzzheavier', specific_folder_id=parent_id)
                if res and parent_id: return f"https://buzzheavier.com/{parent_id}"
            
            # Gofile/Viking: Upload langsung (Gofile folder dihandle di direct_uploader jika perlu, atau root)
            else:
                # Jika ingin Gofile masuk folder juga untuk single file, bisa tambahkan logic create folder di sini.
                # Default: Upload ke root/folderId default.
                res = await uploader.upload(os.path.basename(filepath), 0, mode.lower())
                if res: return list(res.values())[0]

        # === KASUS 3: FOLDER BIASA (Belum Zip) ===
        elif os.path.isdir(filepath):
            if 'bot_msg' in user: await edit_message(user['bot_msg'], f"📂 Uploading Folder to {mode}...")
            
            if mode == 'Buzzheavier':
                uploader.path = os.path.dirname(filepath.rstrip('/'))
                res = await uploader.upload(os.path.basename(filepath), 0, 'buzzheavier')
                if res: return list(res.values())[0]
            # (Tambahkan logic folder Gofile/Viking jika diperlukan)

    except Exception as e:
        LOGGER.error(f"Cloud Upload Error: {e}")
        await send_message(user, f"⚠️ Error: {e}", 'text')
    return None

# --- TASK HANDLERS ---

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path'] 
        
        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            # Gunakan Template Asli
            caption = await format_string(lang.s.ALBUM_TEMPLATE, metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return 

    # 2. LOCAL UPLOAD
    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    
    # 3. TELEGRAM UPLOAD (FIXED: Tambahkan kondisi user_mode)
    elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram':
        if metadata.get('zip_path'):
            zips = metadata['zip_path'] if isinstance(metadata['zip_path'], list) else [metadata['zip_path']]
            for item in zips: await send_message(user, item, 'doc', caption=await format_string(lang.s.ALBUM_TEMPLATE, metadata, user), meta=metadata)
        else: await batch_telegram_upload(metadata, user)
    
    # 4. RCLONE/INDEX UPLOAD (Fallback)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else: await post_simple_message(user, metadata, rclone_link, index_link)
    
    await cleanup(None, metadata, user_dict)

async def playlist_upload(metadata, user):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path']

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            caption = await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
            await cleanup(None, metadata, user)
            return

    # 2. LOCAL UPLOAD
    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    
    # 3. TELEGRAM UPLOAD (FIXED: Cek user_mode agar tidak masuk ke Rclone loop)
    elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zips = metadata['zip_path'] if isinstance(metadata['zip_path'], list) else [metadata['zip_path']]
            for item in zips: await send_message(user, item, 'doc', caption=await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user), meta=metadata)
        else: await batch_telegram_upload(metadata, user)
    
    # 4. RCLONE/INDEX UPLOAD
    else:
        playlist_zip, _, __, ___ = fetch_zip_settings(user)
        # Jika sort aktif dan zip mati, upload per track (Hanya untuk Rclone Mode)
        if bot_set.playlist_sort and not playlist_zip:
            if bot_set.disable_sort_link: await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link: await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError: pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
            if metadata.get('poster_msg'):
                try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified: pass
            else: await post_simple_message(user, metadata, rclone_link, index_link)
            
    await cleanup(None, metadata, user)

async def artist_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'): target = metadata['zip_path']
        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        if link:
            caption = await format_string(lang.s.ARTIST_TEMPLATE, metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            if metadata.get('poster_msg'): await edit_message(metadata['poster_msg'], caption)
            else: await send_message(user, caption, 'text')
            await cleanup(None, metadata, user_dict)
            return

    # 2. LOCAL UPLOAD
    if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
    
    # 3. TELEGRAM UPLOAD (FIXED)
    elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zips = metadata['zip_path'] if isinstance(metadata['zip_path'], list) else [metadata['zip_path']]
            for item in zips: await send_message(user, item, 'doc', caption=await format_string(lang.s.ARTIST_TEMPLATE, metadata, user), meta=metadata)
        else: pass 
    
    # 4. RCLONE/INDEX UPLOAD
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try: await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else: await post_simple_message(user, metadata, rclone_link, index_link)
        
    await cleanup(None, metadata, user_dict)

async def track_upload(metadata, user, disable_link=False):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    upload_success = False
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        link = await upload_to_cloud_handler(metadata['filepath'], user, metadata, user_mode)
        if link:
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            await send_message(user, caption, 'text')
            upload_success = True
            try:
                if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
            except: pass
            return 
            
    if not upload_success:
        if bot_set.upload_mode == 'Local': await local_upload(metadata, user)
        # 2. TELEGRAM UPLOAD (FIXED)
        elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram': await telegram_upload(metadata, user)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
            if not disable_link: await post_simple_message(user, metadata, rclone_link, index_link)
    try: 
        if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
    except: pass

async def rclone_upload(user, realpath):
    path_to_upload = realpath
    base_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    if isinstance(realpath, list): path_to_upload = base_path
    elif isinstance(realpath, str) and realpath.endswith('.zip'): path_to_upload = realpath
    else: path_to_upload = realpath 
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
    r_link, i_link = await create_link(realpath, base_path)
    return r_link, i_link

async def local_upload(metadata, user):
    to_move = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination = os.path.join(Config.LOCAL_STORAGE, os.path.basename(to_move))
    if os.path.exists(destination):
        for item in os.listdir(to_move):
            src_item = os.path.join(to_move, item)
            dest_item = os.path.join(destination, item)
            if os.path.isdir(src_item):
                if not os.path.exists(dest_item): shutil.copytree(src_item, dest_item)
            else: shutil.copy2(src_item, dest_item)
    else: shutil.copytree(to_move, destination)
    shutil.rmtree(to_move)

async def telegram_upload(track, user, batch_mode=False): 
    meta = track.copy()
    meta['batch_mode'] = batch_mode
    if 'cover' in meta and (not meta['cover'] or not os.path.exists(meta['cover'])): meta['cover'] = None 
    user_copy = user
    if batch_mode and 'bot_msg' in user:
        user_copy = user.copy()
        del user_copy['bot_msg']
    filepath = track.get('filepath')
    if not filepath or not os.path.exists(filepath):
        LOGGER.error(f"[UPLOAD FAIL] Path does not exist: '{filepath}'")
        raise FileNotFoundError(f"File not found: {filepath}")
    try: await send_message(user_copy, filepath, 'audio', meta=meta)
    except Exception as e:
        LOGGER.error(f"[UPLOAD ERROR] send_message failed for {filepath}: {e}")
        raise e

async def batch_telegram_upload(metadata, user):
    tasks = []
    if metadata['type'] in ['album', 'playlist']:
        for track in metadata['tracks']:
            if not track.get('filepath'): continue
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                if not track.get('filepath'): continue
                tasks.append(telegram_upload(track, user, batch_mode=True))
    if not tasks: return
    try: await edit_message(user['bot_msg'], f"Mengunggah {len(tasks)} lagu secara paralel...")
    except: pass
    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    async def sem_task(task):
        async with semaphore:
            try: await task 
            except FileNotFoundError: pass
            except Exception as e: LOGGER.error(f"Failed to upload one track during batch: {e}")
    await asyncio.gather(*(sem_task(task) for task in tasks))
