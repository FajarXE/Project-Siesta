# [GANTI FILE: bot/helpers/uploder.py]

import os
import asyncio 
from config import Config 

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *
from bot.logger import LOGGER 

#
#
#  TASK HANDLER
#
#
#

async def track_upload(metadata, user, disable_link=False):
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
    # --- MODIFIKASI: Hapus flag zip lokal, kita gunakan metadata['zip_path'] ---
    # __, _, album_zip = fetch_zip_settings(user_dict) 
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        # --- PERBAIKAN: Cek metadata['zip_path'] dan pastikan itu list ---
        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files] # Ubah string tunggal menjadi list
            
            for item in zip_files: # Loop ini sekarang aman
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        # --- AKHIR PERBAIKAN ---
        else:
            await batch_telegram_upload(metadata, user) # <-- Sekarang akan cepat
    else:
        # (Logika Rclone tetap sama)
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    # Cleanup akan menggunakan metadata['folderpath'] asli (string)
    await cleanup(None, metadata, user_dict)


async def artist_upload(metadata, user):
    user_dict = user.copy()
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        # --- PERBAIKAN: Cek metadata['zip_path'] dan pastikan itu list ---
        if metadata.get('zip_path'): # Menggantikan 'if bot_set.artist_zip:'
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files] # Ubah string tunggal menjadi list

            for item in zip_files: # Loop ini sekarang aman
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        # --- AKHIR PERBAIKAN ---
        else:
            pass # artist telegram uploads are handled by album fucntion
    else:
        # (Logika Rclone tetap sama)
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    # Cleanup akan menggunakan metadata['folderpath'] asli (string)
    await cleanup(None, metadata, user_dict)



async def playlist_upload(metadata, user):
    # --- MODIFIKASI: Hapus flag zip lokal ---
    # playlist_zip, _, __ = fetch_zip_settings(user)
    # is_owner = playlist_zip == bot_set.playlist_zip
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        # --- PERBAIKAN: Cek metadata['zip_path'] dan pastikan itu list ---
        if metadata.get('zip_path'): # Menggantikan 'if playlist_zip:'
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files] # Ubah string tunggal menjadi list
                
            for item in zip_files: # Loop ini sekarang aman
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        # --- AKHIR PERBAIKAN ---
        else:
            await batch_telegram_upload(metadata, user) # <-- Sekarang akan cepat
    else:
        playlist_zip, _, __ = fetch_zip_settings(user) # <-- Dibutuhkan untuk logika rclone
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
            # (Logika Rclone tetap sama)
            rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
            if metadata['poster_msg']:
                try:
                    await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)

    # Cleanup akan menggunakan metadata['folderpath'] asli (string)
    await cleanup(None, metadata, user) # <-- Perbaikan: user, bukan user_dict


#
#
#  CORE
#
#
#

async def rclone_upload(user, realpath):
    """
    Args:
        user: user details
        realpath: full real path to (not used for uploading)
    Returns:
        rclone_link, index_link
    """
    # --- PERBAIKAN: Rclone harus mengunggah file zip atau folder ---
    path_to_upload = realpath
    base_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"

    # Jika realpath adalah list (dari zip split), unggah base path
    if isinstance(realpath, list):
        path_to_upload = base_path
    # Jika realpath adalah file zip tunggal
    elif isinstance(realpath, str) and realpath.endswith('.zip'):
        path_to_upload = realpath
    # Jika ini adalah folder (tidak di-zip)
    else:
        path_to_upload = realpath # Ini sudah benar (path ke folder)

    # Jika path_to_upload adalah file, kita perlu mengunggah ke direktori tujuan
    # Jika path_to_upload adalah direktori, rclone akan menyalin isinya
    
    # Logika rclone copy yang disederhanakan:
    # Selalu salin seluruh folder unduhan pengguna
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
    
    # Buat link berdasarkan path asli (bisa berupa folder atau file zip)
    r_link, i_link = await create_link(realpath, base_path)
    # --- AKHIR PERBAIKAN ---
    return r_link, i_link


async def local_upload(metadata, user):
    """
    Copies directory to local storage and merges contents if the destination exists.
    Args:
        metadata: metadata dict of item
        user: user details
    """
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


async def telegram_upload(track, user, batch_mode=False): # <-- MODIFIKASI: Menambahkan batch_mode
    """
    Only upload a single track
    Args:
        track: track metadata
        batch_mode: (bool) If True, disables individual progress bar in send_message
    """
    # --- MODIFIKASI: Salin 'meta' dan tambahkan 'batch_mode' ---
    meta = track.copy()
    meta['batch_mode'] = batch_mode
    
    # Hapus bot_msg dari user jika dalam mode batch (agar tidak mengedit status)
    user_copy = user
    if batch_mode and 'bot_msg' in user:
        user_copy = user.copy()
        del user_copy['bot_msg']
    # --- BATAS MODIFIKASI ---

    await send_message(user_copy, track['filepath'], 'audio', meta=meta)


async def batch_telegram_upload(metadata, user):
    """
    Args:
        metadata: full metadata
        user: user details
    """
    
    # --- MODIFIKASI DIMULAI (Upload Konkuren/Paralel) ---
    
    tasks = []
    if metadata['type'] == 'album' or metadata['type'] == 'playlist':
        for track in metadata['tracks']:
            # Beri tahu telegram_upload ini adalah mode batch
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                tasks.append(telegram_upload(track, user, batch_mode=True))
    
    if not tasks:
        return

    # Perbarui pesan status sebelum memulai batch upload
    await edit_message(user['bot_msg'], f"Mengunggah {len(tasks)} lagu secara paralel...")

    # Buat Semaphore (Sama seperti di utils.py)
    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)
    
    async def sem_task(task):
        async with semaphore:
            try:
                await task 
            except FileNotFoundError:
                LOGGER.warning(f"File not found during batch upload, skipping.")
            except Exception as e:
                LOGGER.error(f"Failed to upload one track during batch: {e}")

    # Jalankan semua tugas unggah secara bersamaan (dibatasi oleh MAX_WORKERS)
    await asyncio.gather(*(sem_task(task) for task in tasks))
    # --- MODIFIKASI SELESAI ---
