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

# --- CAPTION GENERATOR (BOLD + SMALL CAPS) ---
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
    
    # 1. Tentukan Token & Tipe Upload
    token = None
    upload_type = None
    
    if mode == 'Gofile':
        token = user_data.get('gofile_token')
        upload_type = 'gofile'
    elif mode == 'Pixeldrain':
        token = user_data.get('pixeldrain_token')
        upload_type = 'pixeldrain'
    elif mode == 'Buzzheavier':
        token = user_data.get('buzzheavier_token')
        upload_type = 'buzzheavier'
    elif mode == 'Vikingfiles':
        token = user_data.get('viking_token')
        upload_type = 'viking'

    # Cek Token
    if not token:
        await send_message(user, f"⚠️ <b>{mode} Token Missing!</b>\nPlease set it using `/set_{mode.lower()} token`\nFalling back to Telegram...", 'text')
        return None

    # Siapkan Dictionary Token untuk DirectUpload
    server_dict = {
        "gofile": {"api": user_data.get('gofile_token')},
        "pixeldrain": {"api": user_data.get('pixeldrain_token')},
        "buzzheavier": {"api": user_data.get('buzzheavier_token')},
        "vikingfiles": {"api": user_data.get('viking_token')}
    }
    
    listener = FakeListener(server_dict)
    # DirectUpload butuh path direktori induk untuk inisialisasi
    base_path = os.path.dirname(filepath) if os.path.isfile(filepath) else os.path.dirname(filepath.rstrip('/'))
    uploader = DirectUpload(listener=listener, path=base_path)

    try:
        # A. KASUS FOLDER (ALBUM / PLAYLIST)
        if os.path.isdir(filepath):
            # KHUSUS GOFILE: Support Folder Native (Rapi)
            if mode == 'Gofile':
                if 'bot_msg' in user: 
                    await edit_message(user['bot_msg'], f"📂 Creating Folder on Gofile...")
                
                # 1. Dapatkan Root ID
                root_id = await uploader.gofile_get_root(token)
                
                # 2. Buat Folder Baru
                album_name = os.path.basename(filepath)
                new_folder = await uploader.gofile_create_folder_async(token, root_id, album_name)
                
                if new_folder:
                    folder_id = new_folder['id']
                    final_link = new_folder['code'] # Code folder untuk link
                    
                    # 3. Kumpulkan file
                    files_to_upload = []
                    for root, dirs, files in os.walk(filepath):
                        for file in files:
                            if file.lower().endswith(('.mp3', '.flac', '.m4a', '.wav', '.jpg', '.jpeg', '.png', '.zip', '.rar')):
                                files_to_upload.append(os.path.join(root, file))
                    
                    total_files = len(files_to_upload)
                    
                    # 4. Upload Loop ke Folder Baru
                    for index, file_path in enumerate(files_to_upload, 1):
                        if 'bot_msg' in user and index % 2 != 0:
                             await edit_message(user['bot_msg'], f"🚀 Uploading ({index}/{total_files}) to Gofile Folder...\nFile: `{os.path.basename(file_path)}`")
                        
                        # Set path uploader ke lokasi file saat ini (penting jika rekursif)
                        uploader.path = os.path.dirname(file_path)
                        await uploader.upload(os.path.basename(file_path), 0, 'gofile', specific_folder_id=folder_id)
                    
                    return f"https://gofile.io/d/{final_link}"
            
            # SELAIN GOFILE: Auto-ZIP (Pixeldrain dll tidak support folder upload mudah)
            else:
                if 'bot_msg' in user: 
                    await edit_message(user['bot_msg'], f"🗜️ Zipping Album for {mode}...")
                
                # Buat ZIP dari folder
                archive_path = shutil.make_archive(filepath, 'zip', filepath)
                
                # Update variable filepath ke file .zip baru
                filepath = archive_path 
                
                # Update path uploader karena file zip ada di luar folder asli
                uploader.path = os.path.dirname(filepath)
                
                if 'bot_msg' in user: 
                    await edit_message(user['bot_msg'], f"🚀 Uploading ZIP to {mode}...")
                
                # Upload ZIP
                res = await uploader.upload(os.path.basename(filepath), 0, upload_type)
                
                # Hapus ZIP setelah upload
                if os.path.exists(filepath): 
                    os.remove(filepath)
                
                if res: 
                    return list(res.values())[0]

        # B. KASUS SINGLE FILE (TRACK)
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
#
#  TASK HANDLERS
#
#
#

async def track_upload(metadata, user, disable_link=False):
    # Cek Mode User
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    upload_success = False

    # 1. CLOUD UPLOAD (Gofile/Pixel/Buzz/Viking)
    if user_mode in ['Gofile', 'Pixeldrain', 'Buzzheavier', 'Vikingfiles']:
        link = await upload_to_cloud_handler(metadata['filepath'], user, metadata, user_mode)
        
        if link:
            # Gunakan Simple Text untuk Track
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            await send_message(user, caption, 'text')
            
            upload_success = True
            try:
                if os.path.exists(metadata['filepath']):
                    os.remove(metadata['filepath'])
            except: pass
            return 

    # 2. STANDARD UPLOAD (Telegram/Local/Rclone)
    if not upload_success:
        if bot_set.upload_mode == 'Local':
            await local_upload(metadata, user)
        elif bot_set.upload_mode == 'Telegram' or user_mode == 'Telegram':
            await telegram_upload(metadata, user)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
            if not disable_link:
                await post_simple_message(user, metadata, rclone_link, index_link)

    # Cleanup
    try:
        if os.path.exists(metadata['filepath']):
            os.remove(metadata['filepath'])
    except Exception:
        pass
        

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Pixeldrain', 'Buzzheavier', 'Vikingfiles']:
        # Tentukan target upload (Folder atau Zip)
        target = metadata.get('folderpath') 
        # Jika user mengaktifkan ZIP di settings, target mungkin sudah jadi ZIP
        if metadata.get('zip_path'):
             # Jika zip_path adalah list (split zip), ambil yang pertama atau handle khusus
             # Untuk cloud, kita asumsikan zip tunggal atau folder
             if isinstance(metadata['zip_path'], str):
                 target = metadata['zip_path']
             elif isinstance(metadata['zip_path'], list):
                 target = metadata['zip_path'][0] # Ambil part 1 atau handle loop jika perlu

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            # Gunakan Caption Detail (Bold)
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return 

    # 2. STANDARD UPLOAD
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files] 
            
            for item in zip_files: 
                await send_message(user, item, 'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        # Rclone Logic
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def artist_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')

    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Pixeldrain', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'):
             target = metadata['zip_path'] if isinstance(metadata['zip_path'], str) else metadata['zip_path'][0]

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return

    # 2. STANDARD UPLOAD
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]

            for item in zip_files:
                await send_message(user, item, 'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            pass 
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata.get('poster_msg'):
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def playlist_upload(metadata, user):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    # 1. CLOUD UPLOAD
    if user_mode in ['Gofile', 'Pixeldrain', 'Buzzheavier', 'Vikingfiles']:
        target = metadata.get('folderpath')
        if metadata.get('zip_path'):
             target = metadata['zip_path'] if isinstance(metadata['zip_path'], str) else metadata['zip_path'][0]

        link = await upload_to_cloud_handler(target, user, metadata, user_mode)
        
        if link:
            caption = create_cloud_caption(metadata)
            caption += f"\n\n🔗 <b>{user_mode.upper()} LINK:</b>\n{link}"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user)
            return

    # 2. STANDARD UPLOAD
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'): 
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]
                
            for item in zip_files: 
                await send_message(user, item, 'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        # Rclone Logic
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
#
#  CORE
#
#
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
