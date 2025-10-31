import os
import asyncio # <-- MODIFIKASI: Ditambahkan
from config import Config # <-- MODIFIKASI: Ditambahkan

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *
from bot.logger import LOGGER # <-- MODIFIKASI: Ditambahkan

#
#
#  TASK HANDLER
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
    __, _, album_zip = fetch_zip_settings(user_dict)
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if album_zip:
            for item in metadata['folderpath']:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
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
        if bot_set.artist_zip:
            for item in metadata['folderpath']:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            pass # artist telegram uploads are handled by album fucntion
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)



async def playlist_upload(metadata, user):
    playlist_zip, _, __ = fetch_zip_settings(user)
    is_owner = playlist_zip == bot_set.playlist_zip
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if playlist_zip:
            for item in metadata['folderpath']:
                await send_message(user,item,'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
    else:
        if bot_set.playlist_sort and not playlist_zip:
            if bot_set.disable_sort_link:
                await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                for track in metadata['tracks']:
                    try:
                        rclone_link, index_link = await rclone_upload(user, track['filepath'])
                        if not bot_set.disable_sort_link:
                            await post_simple_message(user, track, rclone_link, index_link)
                    except ValueError: # might try to upload track which is not available
                        pass
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
            if metadata['poster_msg']:
                try:
                    await edit_art_poster(metadata, user, rclone_link, index_link, await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)

#
#
#  CORE
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
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
    r_link, i_link = await create_link(realpath, Config.DOWNLOAD_BASE_DIR + f"/{user['r_id']}/")
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
    
    # Hapus bot_msg dari user jika dalam mode batch
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
