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

# Import DirectUploader
from ..modules.direct_uploader import DirectUpload

# --- HELPER CLASS ---
class FakeListener:
    def __init__(self, user_dict):
        self.user_dict = user_dict
        self.extra_details = {} 
        self.is_cancelled = False 

    async def onUploadError(self, error):
        LOGGER.error(f"Cloud Upload Error: {error}")
        return str(error)

# --- CAPTION GENERATOR ---
def create_cloud_caption(metadata):
    title = metadata.get('title', 'Unknown')
    artist = metadata.get('artist', 'Unknown')
    date = metadata.get('date') or metadata.get('release_date') or 'Unknown'
    
    if 'tracks' in metadata:
        total_tracks = len(metadata['tracks'])
    else:
        total_tracks = metadata.get('totaltracks', 1)
        
    total_volumes = metadata.get('total_volumes')
    if not total_volumes:
        if 'tracks' in metadata and metadata['tracks']:
            try:
                discs = {t.get('disc_number', t.get('disc', 1)) for t in metadata['tracks']}
                total_volumes = len(discs)
            except:
                total_volumes = 1
        else:
            total_volumes = 1

    quality = metadata.get('quality', 'Unknown')
    provider = metadata.get('provider', 'Unknown')
    explicit = str(metadata.get('explicit', False))

    text = (
        f"<b>ᴛɪᴛʟᴇ</b> : {title}\n"
        f"<b>ᴀʀᴛɪsᴛ</b> : {artist}\n"
        f"<b>ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ</b> : {date}\n"
        f"<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs</b> : {total_tracks}\n"
        f"<b>ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs</b> : {total_volumes}\n"
        f"<b>ǫᴜᴀʟɪᴛʏ</b> : {quality}\n"
        f"<b>ᴘʀᴏᴠɪᴅᴇʀ</b> : {provider}\n"
        f"<b>ᴇxᴘʟɪᴄɪᴛ</b> : {explicit}"
    )
    return text


# --- GENERIC CLOUD UPLOADER HANDLER ---
async def upload_to_cloud_handler(filepath, user, metadata, mode):
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    
    token = None
    upload_type = None
    
    if mode == 'Gofile':
        token = user_data.get('gofile_token')
        upload_type = 'gofile'
    elif mode == 'Buzzheavier':
        token = user_data.get('buzzheavier_token')
        upload_type = 'buzzheavier'
    elif mode == 'Vikingfiles':
        token = user_data.get('viking_token')
        upload_type = 'viking'

    if not token:
        await send_message(user, f"⚠️ <b>{mode} Token Missing!</b>\nPlease set it using `/set_{mode.lower()} token`\nFalling back to Telegram...", 'text')
        return None

    # Siapkan Dictionary Token
    server_dict = {
        "gofile": {"api": user_data.get('gofile_token')},
        "buzzheavier": {"api": user_data.get('buzzheavier_token')},
        "vikingfiles": {"api": user_data.get('viking_token')}
    }
    
    listener = FakeListener(server_dict)
    # Tentukan base path awal
    base_path = os.path.dirname(filepath) if os.path.isfile(filepath) else os.path.dirname(filepath.rstrip('/'))
    uploader = DirectUpload(listener=listener, path=base_path)

    try:
        # A. KASUS FOLDER (ALBUM / PLAYLIST)
        if os.path.isdir(filepath):
            
            # --- 1. GOFILE (SUPPORT FOLDER API) ---
            if mode == 'Gofile':
                if 'bot_msg' in user: 
                    await edit_message(user['bot_msg'], f"📂 Creating Folder on Gofile...")
                
                root_id = await uploader.gofile_get_root(token)
                album_name = os.path.basename(filepath)
                new_folder = await uploader.gofile_create_folder_async(token, root_id, album_name)
                
                if new_folder:
                    folder_id = new_folder['id']
                    final_link = new_folder['code'] 
                    
                    files_to_upload = []
                    for root, dirs, files in os.walk(filepath):
                        for file in files:
                            if file.lower().endswith(('.mp3', '.flac', '.m4a', '.wav', '.jpg', '.jpeg', '.png', '.zip', '.rar')):
                                files_to_upload.append(os.path.join(root, file))
                    
                    total_files = len(files_to_upload)
                    for index, file_path in enumerate(files_to_upload, 1):
                        if 'bot_msg' in user and index % 2 != 0:
                             await edit_message(user['bot_msg'], f"🚀 Uploading ({index}/{total_files}) to Gofile Folder...\nFile: `{os.path.basename(file_path)}`")
                        
                        uploader.path = os.path.dirname(file_path)
                        await uploader.upload(os.path.basename(file_path), 0, 'gofile', specific_folder_id=folder_id)
                    
                    return f"https://gofile.io/d/{final_link}"
            
            # --- 2. BUZZHEAVIER & VIKINGFILES (NON-ZIP / MULTI LINKS) ---
            else:
                if 'bot_msg' in user: 
                    await edit_message(user['bot_msg'], f"📂 Reading files for {mode}...")
                
                files_to_upload = []
                for root, dirs, files in os.walk(filepath):
                    for file in files:
                        if file.lower().endswith(('.mp3', '.flac', '.m4a', '.wav', '.jpg', '.jpeg', '.png', '.zip', '.rar')):
                            files_to_upload.append(os.path.join(root, file))
                
                total_files = len(files_to_upload)
                generated_links = []
                
                for index, file_path in enumerate(files_to_upload, 1):
                    file_name = os.path.basename(file_path)
                    if 'bot_msg' in user and index % 2 != 0:
                         await edit_message(user['bot_msg'], f"🚀 Uploading ({index}/{total_files}) to {mode}...\nFile: `{file_name}`")
                    
                    # Update path uploader ke folder file saat ini
                    uploader.path = os.path.dirname(file_path)
                    
                    # Upload
                    res = await uploader.upload(file_name, 0, upload_type)
                    
                    if res:
                        # Ambil link dari result (e.g. {'Vikingfiles': 'url'})
                        link = list(res.values())[0]
                        generated_links.append(f"• {file_name}: {link}")
                
                if generated_links:
                    return "\n".join(generated_links)
                else:
                    return None

        # B. KASUS SINGLE FILE (TRACK / ZIP yang sudah ada)
        else:
            if 'bot_msg' in user: 
                await edit_message(user['bot_msg'], f"🚀 Uploading to {mode}...")
            
            res = await uploader.upload(os.path.basename(filepath), 0, upload_type)
            if res: 
                return list(res.values())[0]

    except Exception as e:
        LOGGER.error(f"Cloud Upload Error ({mode}): {e}")
        await send_message(user, f"⚠️ {mode} Error: {e}", 'text')
    
    return None


#
#  TASK HANDLERS
#

async def track_upload(metadata, user, disable_link=False):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    upload_success = False

    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        link = await upload_to_cloud_handler(metadata['filepath'], user, metadata, user_mode)
        
        if link:
            # Simple Text untuk Track
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            await send_message(user, caption, 'text')
            
            upload_success = True
            try:
                if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
            except: pass
            return 

    if not upload_success:
        if bot_set.upload_mode == 'Local':
            await local_upload(metadata, user)
        elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram':
            await telegram_upload(metadata, user)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
            if not disable_link:
                await post_simple_message(user, metadata, rclone_link, index_link)

    try:
        if os.path.exists(metadata['filepath']): os.remove(metadata['filepath'])
    except: pass
        

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        # Gunakan folder asli (jangan dipaksa zip jika user tidak minta)
        target = metadata.get('folderpath')
        
        # Kecuali jika user memang mengaktifkan "ALBUM ZIP: ON" di pengaturan, maka gunakan zip
        if metadata.get('zip_path'):
             target = metadata['zip_path'] if isinstance(metadata['zip_path'], str) else metadata['zip_path'][0]

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            # Caption Detail untuk Album
            caption = create_cloud_caption(metadata)
            
            # Jika link berupa list (newline separated), tambahkan header 'LINKS' jamak
            if '\n' in link:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINKS:</b>\n{link}"
            else:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return 

    # Fallback Standard
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files] 
            for item in zip_files: 
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else:
            await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def artist_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')

    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'):
             target = metadata['zip_path'] if isinstance(metadata['zip_path'], str) else metadata['zip_path'][0]

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            caption = create_cloud_caption(metadata)
            if '\n' in link:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINKS:</b>\n{link}"
            else:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return

    # Fallback
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str): zip_files = [zip_files]
            for item in zip_files:
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else:
            pass 
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified: pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def playlist_upload(metadata, user):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    if user_mode in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'):
             target = metadata['zip_path'] if isinstance(metadata['zip_path'], str) else metadata['zip_path'][0]

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            caption = create_cloud_caption(metadata)
            if '\n' in link:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINKS:</b>\n{link}"
            else:
                caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user)
            return

    # Fallback
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]
            for item in zip_files: 
                await send_message(user, item, 'doc', caption=await create_simple_text(metadata, user), meta=metadata)
        else:
            await batch_telegram_upload(metadata, user)
    else:
        playlist_zip, _, __, ___ = fetch_zip_settings(user)
        if bot_set.playlist_sort and not playlist_zip:
            if bot_set.disable_sort_link:
                await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link:
                            await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError:
                        pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
            if metadata.get('poster_msg'):
                try:
                    await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user)


#
#  CORE
#

async def rclone_upload(user, realpath):
    path_to_upload = realpath
    base_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"

    if isinstance(realpath, list):
        path_to_upload = base_path
    elif isinstance(realpath, str) and realpath.endswith('.zip'):
        path_to_upload = realpath
    else:
        path_to_upload = realpath 

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
                if not os.path.exists(dest_item):
                    shutil.copytree(src_item, dest_item)
            else:
                shutil.copy2(src_item, dest_item)
    else:
        shutil.copytree(to_move, destination)
    
    shutil.rmtree(to_move)

async def telegram_upload(track, user, batch_mode=False): 
    meta = track.copy()
    meta['batch_mode'] = batch_mode
    
    if 'cover' in meta and (not meta['cover'] or not os.path.exists(meta['cover'])):
        meta['cover'] = None 
    
    user_copy = user
    if batch_mode and 'bot_msg' in user:
        user_copy = user.copy()
        del user_copy['bot_msg']
    
    filepath = track.get('filepath')

    if not filepath or not os.path.exists(filepath):
        LOGGER.error(f"[UPLOAD FAIL] Path does not exist: '{filepath}'")
        raise FileNotFoundError(f"File not found: {filepath}")

    try:
        await send_message(user_copy, filepath, 'audio', meta=meta)
    except Exception as e:
        LOGGER.error(f"[UPLOAD ERROR] send_message failed for {filepath}: {e}")
        raise e


async def batch_telegram_upload(metadata, user):
    tasks = []
    if metadata['type'] in ['album', 'playlist']:
        for track in metadata['tracks']:
            if not track.get('filepath'):
                continue
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
            
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                if not track.get('filepath'): continue
                tasks.append(telegram_upload(track, user, batch_mode=True))
    
    if not tasks:
        LOGGER.warning("[BATCH] No valid tasks created.")
        return

    try:
        await edit_message(user['bot_msg'], f"Mengunggah {len(tasks)} lagu secara paralel...")
    except: pass

    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    
    async def sem_task(task):
        async with semaphore:
            try:
                await task 
            except FileNotFoundError:
                pass
            except Exception as e:
                LOGGER.error(f"Failed to upload one track during batch: {e}")

    await asyncio.gather(*(sem_task(task) for task in tasks))
