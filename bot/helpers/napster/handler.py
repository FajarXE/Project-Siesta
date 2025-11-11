# [BUAT FILE BARU: bot/helpers/napster/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata,
    custom_url_parse
)
from .manager import NapsterError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

async def start_napster(url: str, user: dict):
    """Handler utama untuk link Napster."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        elif media_type == 'album':
            await start_album(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media Napster '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Napster handler: {e}\n{traceback.format_exc()}")
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    client = user['napster_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"Napster track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    bitrate = track_meta.get('download_bitrate')
    codec = track_meta.get('download_codec')
    if not bitrate or not codec:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan Napster track {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- LOGIKA UNDUH Napster ---
    try:
        # 1. Dapatkan URL Stream (Async)
        download_url = await asyncio.to_thread(
            client.get_stream_url,
            bitrate,
            codec,
            item_id # item_id adalah track_id
        )
        
        if not download_url:
            raise NapsterError(f"Gagal mendapatkan URL unduhan untuk {item_id}")
            
        # Pastikan direktori ada
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 2. Unduh file (Ini adalah unduhan HTTP sederhana, tidak ada DRM)
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url) as response:
                response.raise_for_status()
                async with aiofiles.open(track_meta['filepath'], "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

    # --- PERBAIKAN: Menyembunyikan Error 404 dari Log ---
    except Exception as e:
        is_404_error = False
        if isinstance(e, aiohttp.ClientResponseError):
            if e.status == 404:
                is_404_error = True
        
        if is_404_error:
            # Ini adalah error 404 yang ingin kita sembunyikan.
            # Jangan log sebagai ERROR, cukup sebagai DEBUG (tersembunyi).
            LOGGER.debug(f"Napster dl_track 404 (diredam) untuk {item_id}: {e}")
        else:
            # Ini adalah error lain yang valid, log seperti biasa.
            LOGGER.error(f"Napster dl_track gagal untuk {item_id}: {e}")
        
        return False
    # --- BATAS PERBAIKAN ---

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        # Kita masih mungkin mendapatkan error ini jika file gagal diunduh (karena 404)
        LOGGER.debug(f"[Errno 2] File not found setelah download Napster (diredam): {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Napster: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album.
    """
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Napster: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        # Kirim track_meta (pre_data) ke start_track agar tidak perlu fetch ulang
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [album_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Napster yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
