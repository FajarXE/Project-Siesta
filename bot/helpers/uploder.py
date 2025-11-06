# [GANTI FILE: bot/helpers/uploder.py]

import os
import asyncio 
from config import Config 

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *
from bot.logger import LOGGER 

# --- TAMBAHAN: Impor Gofile Uploader ---
try:
    from ..helpers.gofile_api import gofile_batch_upload
except ImportError:
    # Fallback jika file gofile_api.py belum ada
    LOGGER.warning("Uploader: Gagal mengimpor 'gofile_batch_upload'. Unggahan Gofile pribadi tidak akan berfungsi.")
    async def gofile_batch_upload(*args, **kwargs):
        raise NotImplementedError("Modul gofile_api.py tidak ditemukan.")
# --- BATAS TAMBAHAN ---

#
#
#  TASK HANDLER
#
#
#

async def track_upload(metadata, user, disable_link=False):
    
    # --- PERBAIKAN: Ganti 'database.get_user' dengan 'bot_set.user_data.get' ---
    user_settings = bot_set.user_data.get(user['user_id'], {})
    gofile_key = user_settings.get('gofile_api_key')
    gofile_folder = user_settings.get('gofile_folder_id')

    if gofile_key and gofile_folder:
        await edit_message(user['bot_msg'], f"Mengunggah 1 lagu ke Gofile pribadi Anda...")
        file_list = [{
            'filepath': metadata['filepath'],
            'filename': os.path.basename(metadata['filepath'])
        }]
        
        try:
            links = await gofile_batch_upload(file_list, gofile_key, gofile_folder, user['bot_msg'])
            link_text = "\n".join(links)
            await send_message(user, f"Unggahan Gofile Selesai:\n{link_text}")
        except Exception as e:
            await send_message(user, f"Gagal mengunggah ke Gofile pribadi: {e}")
        
        try:
            os.remove(metadata['filepath'])
        except FileNotFoundError:
            pass
        return 
    # --- AKHIR PERBAIKAN ---

    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        await telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
        if not disable_link:
            await post_simple_message(user, metadata, rclone_link, index_link)

    try:
        os.remove(metadata['filepath'])
    except FileNotFoundError:
        pass
        


async def album_upload(metadata, user):
    user_dict = user.copy()

    # --- PERBAIKAN: Ganti 'database.get_user' dengan 'bot_set.user_data.get' ---
    user_settings = bot_set.user_data.get(user['user_id'], {})
    gofile_key = user_settings.get('gofile_api_key')
    gofile_folder = user_settings.get('gofile_folder_id')

    if gofile_key and gofile_folder:
        await edit_message(user['bot_msg'], f"Mengunggah {metadata['totaltracks']} lagu ke Gofile pribadi Anda...")
        
        file_list = []
        for track in metadata['tracks']:
            file_list.append({
                'filepath': track['filepath'],
                'filename': os.path.basename(track['filepath'])
            })
            
        try:
            links = await gofile_batch_upload(file_list, gofile_key, gofile_folder, user['bot_msg'])
            
            if len(links) > 10:
                link_file_path = f"{metadata['folderpath']}/gofile_links.txt"
                os.makedirs(os.path.dirname(link_file_path), exist_ok=True)
                with open(link_file_path, 'w') as f:
                    f.write("\n".join(links))
                await send_message(user, link_file_path, 'doc', caption=f"Link Gofile untuk {metadata['title']}")
            else:
                await send_message(user, f"Unggahan Gofile Selesai untuk {metadata['title']}:\n" + "\n".join(links))
        except Exception as e:
            await send_message(user, f"Gagal mengunggah ke Gofile pribadi: {e}")

        await cleanup(None, metadata, user_dict)
        return
    # --- AKHIR PERBAIKAN ---

    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]
            
            for item in zip_files:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def artist_upload(metadata, user):
    user_dict = user.copy()
    
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]

            for item in zip_files:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            pass 
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)



async def playlist_upload(metadata, user):

    # --- PERBAIKAN: Ganti 'database.get_user' dengan 'bot_set.user_data.get' ---
    user_settings = bot_set.user_data.get(user['user_id'], {})
    gofile_key = user_settings.get('gofile_api_key')
    gofile_folder = user_settings.get('gofile_folder_id')

    if gofile_key and gofile_folder:
        await edit_message(user['bot_msg'], f"Mengunggah {metadata['totaltracks']} lagu ke Gofile pribadi Anda...")
        
        file_list = []
        for track in metadata['tracks']:
            file_list.append({
                'filepath': track['filepath'],
                'filename': os.path.basename(track['filepath'])
            })
            
        try:
            links = await gofile_batch_upload(file_list, gofile_key, gofile_folder, user['bot_msg'])
            
            if len(links) > 10:
                link_file_path = f"{metadata['folderpath']}/gofile_links.txt"
                os.makedirs(os.path.dirname(link_file_path), exist_ok=True)
                with open(link_file_path, 'w') as f:
                    f.write("\n".join(links))
                await send_message(user, link_file_path, 'doc', caption=f"Link Gofile untuk {metadata['title']}")
            else:
                await send_message(user, f"Unggahan Gofile Selesai untuk {metadata['title']}:\n" + "\n".join(links))
        except Exception as e:
            await send_message(user, f"Gagal mengunggah ke Gofile pribadi: {e}")

        await cleanup(None, metadata, user)
        return
    # --- AKHIR PERBAIKAN ---

    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files]
            for item in zip_files:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        playlist_zip, _, __ = fetch_zip_settings(user)
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
            if metadata['poster_msg']:
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
    user_copy = user
    if batch_mode and 'bot_msg' in user:
        user_copy = user.copy()
        del user_copy['bot_msg']
    await send_message(user_copy, track['filepath'], 'audio', meta=meta)


async def batch_telegram_upload(metadata, user):
    tasks = []
    if metadata['type'] == 'album' or metadata['type'] == 'playlist':
        for track in metadata['tracks']:
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                tasks.append(telegram_upload(track, user, batch_mode=True))
    if not tasks:
        return
    await edit_message(user['bot_msg'], f"Mengunggah {len(tasks)} lagu secara paralel...")
    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    async def sem_task(task):
        async with semaphore:
            try:
                await task 
            except FileNotFoundError:
                LOGGER.warning(f"File not found during batch upload, skipping.")
            except Exception as e:
                LOGGER.error(f"Failed to upload one track during batch: {e}")
    await asyncio.gather(*(sem_task(task) for task in tasks))
