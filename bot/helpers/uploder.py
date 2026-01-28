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

# --- HELPER CLASS ---
class FakeListener:
    def __init__(self, user_id, gofile_token):
        self.user_dict = {
            "gofile": {
                "api": gofile_token,
                "folder_id": "" 
            }
        }
        self.extra_details = {} 
        self.is_cancelled = False 

    async def onUploadError(self, error):
        LOGGER.error(f"Gofile Upload Error: {error}")
        return str(error)

# --- CAPTION GENERATOR (BOLD + SMALL CAPS) ---
def create_gofile_caption(metadata):
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

    # GUNAKAN HTML BOLD <b>...</b>
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


# --- GOFILE HANDLER (FOLDER SUPPORT) ---
async def upload_to_gofile_handler(filepath, user, metadata):
    user_id = user['user_id']
    user_data = bot_set.user_data.get(user_id, {})
    token = user_data.get('gofile_token')

    if not token:
        await send_message(user, "⚠️ <b>Gofile Token Missing!</b>\nPlease set it using <code>/set_gofile token</code>\nFalling back to Telegram...", 'text')
        return None 

    # Helper upload satu file dengan opsi folder target
    async def _upload_single_file(path_to_file, target_folder_id=None):
        try:
            listener = FakeListener(user_id, token)
            uploader = DirectUpload(
                listener=listener, 
                name=os.path.basename(path_to_file), 
                path=os.path.dirname(path_to_file)
            )
            filesize = os.path.getsize(path_to_file)
            
            # Panggil upload dengan specific_folder_id
            result = await uploader.upload(os.path.basename(path_to_file), filesize, "gf", specific_folder_id=target_folder_id)
            
            if result and isinstance(result, dict):
                return result.get('Gofile')
        except Exception as e:
            LOGGER.error(f"Gagal upload file {os.path.basename(path_to_file)}: {e}")
        return None

    try:
        # KASUS 1: FOLDER (Album/Playlist) -> Buat Folder Baru -> Upload -> Return Link Folder
        if os.path.isdir(filepath):
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], f"📂 Creating Album Folder on Gofile...")

            # 1. Siapkan Uploader Instance
            temp_listener = FakeListener(user_id, token)
            temp_uploader = DirectUpload(listener=temp_listener)

            # 2. Dapatkan Root Folder User
            root_id = await temp_uploader.get_root_folder(token)
            if not root_id:
                await send_message(user, "⚠️ Gagal mendapatkan Root Folder Gofile. Mengunggah ke Root...", 'text')
                # Jika gagal, parent_id kosong (masuk root), tapi file akan berserakan.
            
            # 3. Buat Folder Baru (Nama Folder = Nama Album)
            album_folder_name = os.path.basename(filepath)
            new_folder_data = await temp_uploader.create_folder(token, root_id, album_folder_name)
            
            target_folder_id = None
            final_link = None
            
            if new_folder_data:
                target_folder_id = new_folder_data.get('id')
                final_link = new_folder_data.get('code') # Ini adalah kode link folder (https://gofile.io/d/CODE)
                if final_link:
                    final_link = f"https://gofile.io/d/{final_link}"
            
            # 4. Kumpulkan File
            files_to_upload = []
            for root, dirs, files in os.walk(filepath):
                for file in files:
                    if file.lower().endswith(('.mp3', '.flac', '.m4a', '.wav', '.jpg', '.jpeg', '.png', '.zip', '.rar')):
                        files_to_upload.append(os.path.join(root, file))
            
            total_files = len(files_to_upload)
            
            # 5. Loop Upload ke Folder Baru
            for index, file_path in enumerate(files_to_upload, 1):
                if 'bot_msg' in user and index % 2 != 0:
                     await edit_message(user['bot_msg'], f"🚀 Uploading ({index}/{total_files}) to Gofile Folder...\nFile: `{os.path.basename(file_path)}`")
                
                # Upload ke target_folder_id
                await _upload_single_file(file_path, target_folder_id)
                # Kita tidak perlu menyimpan link file individual karena kita akan memberikan link folder

            return final_link # Kembalikan Link Folder Utama

        # KASUS 2: SINGLE FILE
        else:
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], f"🚀 Uploading to Gofile...\nFile: `{os.path.basename(filepath)}`")
            
            link = await _upload_single_file(filepath)
            return link

    except Exception as e:
        LOGGER.error(f"Gofile Handler Error: {e}")
        await send_message(user, f"⚠️ Gofile Error: {e}\nFalling back to Telegram...", 'text')
        return None


# --- TASK HANDLER UTAMA ---

async def track_upload(metadata, user, disable_link=False):
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    upload_success = False

    if user_mode == 'Gofile':
        gofile_link = await upload_to_gofile_handler(metadata['filepath'], user, metadata)
        
        if gofile_link:
            # Format Track Simple
            caption = await create_simple_text(metadata, user)
            caption += f"\n\n🔗 <b>GOFILE LINK:</b>\n{gofile_link}"
            
            await send_message(user, caption, 'text')
            
            upload_success = True
            try:
                if os.path.exists(metadata['filepath']):
                    os.remove(metadata['filepath'])
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
        if os.path.exists(metadata['filepath']):
            os.remove(metadata['filepath'])
    except Exception:
        pass
        

async def album_upload(metadata, user):
    user_dict = user.copy()
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', 'Telegram')
    
    if user_mode == 'Gofile':
        targets = []
        if metadata.get('zip_path'):
            zip_p = metadata['zip_path']
            if isinstance(zip_p, list): targets = zip_p
            else: targets = [zip_p]
        elif metadata.get('folderpath'):
            targets = [metadata['folderpath']]
            
        links = []
        for target in targets:
            link = await upload_to_gofile_handler(target, user, metadata)
            if link: links.append(link)
        
        if links:
            # FORMAT CAPTION BARU (BOLD)
            caption = create_gofile_caption(metadata)
            caption += "\n\n🔗 <b>GOFILE LINKS:</b>\n"
            for l in links:
                caption += f"{l}\n"
            
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

    if user_mode == 'Gofile':
        targets = []
        if metadata.get('zip_path'):
            zip_p = metadata['zip_path']
            if isinstance(zip_p, list): targets = zip_p
            else: targets = [zip_p]
        elif metadata.get('folderpath'):
            targets = [metadata['folderpath']]
            
        links = []
        for target in targets:
            link = await upload_to_gofile_handler(target, user, metadata)
            if link: links.append(link)
        
        if links:
            caption = create_gofile_caption(metadata)
            caption += "\n\n🔗 <b>GOFILE LINKS:</b>\n"
            for l in links:
                caption += f"{l}\n"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user_dict)
            return

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
    
    if user_mode == 'Gofile':
        targets = []
        if metadata.get('zip_path'):
            zip_p = metadata['zip_path']
            if isinstance(zip_p, list): targets = zip_p
            else: targets = [zip_p]
        elif metadata.get('folderpath'):
            targets = [metadata['folderpath']]
            
        links = []
        for target in targets:
            link = await upload_to_gofile_handler(target, user, metadata)
            if link: links.append(link)
        
        if links:
            caption = create_gofile_caption(metadata)
            caption += "\n\n🔗 <b>GOFILE LINKS:</b>\n"
            for l in links:
                caption += f"{l}\n"
            
            if metadata.get('poster_msg'):
                 await edit_message(metadata['poster_msg'], caption)
            else:
                 await send_message(user, caption, 'text')
            
            await cleanup(None, metadata, user)
            return

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
