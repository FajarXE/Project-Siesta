# [GANTI FILE: bot/helpers/uploder.py]

import os
import asyncio
import shutil
from config import Config 
from pyrogram.errors import MessageNotModified

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
        if os.path.exists(metadata['filepath']):
            os.remove(metadata['filepath'])
    except Exception:
        pass
        

async def album_upload(metadata, user):
    user_dict = user.copy()
    
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
        
    elif bot_set.upload_mode == 'Telegram':
        # --- LOGIKA BARU: KIRIM ART POSTER DI TELEGRAM ---
        # Cek apakah setting poster aktif, cover tersedia, dan filenya ada
        if metadata.get('poster_msg') and metadata.get('cover') and os.path.exists(metadata['cover']):
            try:
                # Buat caption ringkas untuk poster
                caption = await create_simple_text(metadata, user)
                # Kirim gambar
                await send_message(user, metadata['cover'], 'pic', caption=caption)
            except Exception as e:
                LOGGER.error(f"Gagal mengirim Art Poster: {e}")
        # ------------------------------------------------

        if metadata.get('zip_path'):
            zip_files = metadata['zip_path']
            if isinstance(zip_files, str):
                zip_files = [zip_files] 
            
            for item in zip_files: 
                # Kirim file ZIP
                await send_message(user, item, 'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            await batch_telegram_upload(metadata, user)
            
    else:
        # Mode Rclone / Lainnya
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        
        if metadata.get('poster_msg'):
            try:
                if metadata.get('cover'):
                    caption = await create_simple_text(metadata, user)
                    await send_message(user, metadata['cover'], 'pic', caption=caption)
                else:
                    await post_simple_message(user, metadata, rclone_link, index_link)
            except Exception:
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
                await send_message(user, item, 'doc', 
                    caption=await create_simple_text(metadata, user),
                    meta=metadata
                )
        else:
            pass # Artist biasanya selalu zip di telegram mode bot ini
    else:
        rclone_link, index_link = await rclone_upload(user, metadata.get('zip_path') or metadata['folderpath'])
        await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user_dict)


async def playlist_upload(metadata, user):
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
        # Rclone playlist logic
        # Kita perlu memanggil fetch_zip_settings di sini jika ingin konsisten, 
        # tapi karena file ini hanya helper uploader, kita asumsikan logic zip sudah di handler.
        # Namun code bawaan anda mengecek bot_set.playlist_sort disini.
        
        # Pengecekan manual sederhana karena kita tidak punya akses langsung ke fetch_zip_settings di scope ini tanpa import
        # (Asumsi metadata sudah membawa info zip_path jika di-zip)
        has_zip = metadata.get('zip_path') is not None

        if bot_set.playlist_sort and not has_zip:
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
            await post_simple_message(user, metadata, rclone_link, index_link)

    await cleanup(None, metadata, user)


#
#  CORE FUNGSI UPLOAD
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
        try:
            del user_copy['bot_msg']
        except KeyError:
            pass
    
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
    # Collect tasks
    if metadata['type'] in ['album', 'playlist']:
        for track in metadata['tracks']:
            # PENTING: Pastikan track dict memiliki filepath sebelum dikirim
            if not track.get('filepath'):
                LOGGER.warning(f"[BATCH SKIP] Track '{track.get('title')}' tidak memiliki filepath. Dilewati.")
                continue
            tasks.append(telegram_upload(track, user, batch_mode=True)) 
            
    elif metadata['type'] == 'artist':
        for album in metadata['albums']:
            for track in album['tracks']:
                if not track.get('filepath'): continue
                tasks.append(telegram_upload(track, user, batch_mode=True))
    
    if not tasks:
        LOGGER.warning("[BATCH] No valid tasks created (all tracks missing filepath?)")
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
                # Error sudah di-log di telegram_upload, pass saja
                pass
            except Exception as e:
                LOGGER.error(f"Failed to upload one track during batch: {e}")

    await asyncio.gather(*(sem_task(task) for task in tasks))
