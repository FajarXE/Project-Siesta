# [GANTI FILE: bot/helpers/highresaudio/handler.py]

import aiofiles
import os
import traceback
import asyncio
import math # Diperlukan untuk progress bar
import requests # Diperlukan untuk unduhan sinkron

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_album_metadata,
    custom_url_parse
)
from .manager import HighResAudioError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

async def start_highresaudio(url: str, user: dict):
    """Handler utama untuk link HighResAudio."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        # HRA-DL.py only supports albums, so do we
        if media_type == 'album':
            # item_id here is the full 'album_url'
            await start_album(item_id, user)
        else:
            raise NotImplementedError(f"Tipe media HighResAudio '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di HighResAudio handler: {e}\n{traceback.format_exc()}")
        raise e 

async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):
    """
    Downloads a single track. track_meta MUST be provided by start_album.
    """
    client = user['highresaudio_api']

    if not track_meta:
        raise HighResAudioError("start_track dipanggil tanpa track_meta (tidak didukung).")
            
    filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
    filepath = sanitize_filepath(filepath)

    download_url = track_meta.get('download_url')
    # This is the internal album ID, not the URL
    album_id_referer = track_meta.get('album_id_referer') 
    
    if not download_url or not album_id_referer:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan HighResAudio track (URL: {download_url}, Referer: {album_id_referer})")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)
    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- DOWNLOAD LOGIC (Unencrypted) ---
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Run synchronous download in a separate thread
        await asyncio.to_thread(
            download_track_unencrypted,
            client, # HighResAudioApi object (with requests session)
            download_url,
            album_id_referer,
            track_meta['filepath']
        )

    except Exception as e:
        LOGGER.error(f"HighResAudio dl_track gagal: {e}\n{traceback.format_exc()}")
        return False
    # --- END DOWNLOAD LOGIC ---

    try:
        await set_metadata(track_meta)
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata HighResAudio: {filepath} -> {e}\n{traceback.format_exc()}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


def download_track_unencrypted(client, url, album_id_referer, temp_location):
    """
    SYNCHRONOUS function to download a HighResAudio file (unencrypted).
    Run in ThreadPoolExecutor by asyncio.to_thread.
    Logic adapted from HRA-DL.py fetchTrack()
    """
    
    try:
        # 1. Get stream data (this uses 'requests' from 'client.s')
        r = client.get_track_stream(url, album_id_referer)
        r.raise_for_status()

        # 2. Download and Write
        with open(temp_location, 'wb') as f:
            for chunk in r.iter_content(chunk_size=32 * 1024):
                if chunk:
                    f.write(chunk)
                    
    except Exception as e:
        # Delete partial file on failure
        if os.path.isfile(temp_location):
            os.remove(temp_location)
        raise e
    
    LOGGER.info(f"HighResAudio: Berhasil mengunduh ke {temp_location}")

def download_booklet(client, url, temp_location):
    """SYNCHRONOUS function to download the PDF booklet."""
    try:
        r = client.get_booklet_stream(url) # Call booklet API method
        r.raise_for_status()
        with open(temp_location, 'wb') as f:
            for chunk in r.iter_content(chunk_size=32 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        if os.path.isfile(temp_location):
            os.remove(temp_location)
        LOGGER.error(f"HighResAudio: Gagal mengunduh booklet: {e}")
        # Don't 'raise e' so we don't fail the whole album download
    
    LOGGER.info(f"HighResAudio: Berhasil mengunduh booklet ke {temp_location}")


async def start_album(album_url: str, user: dict, upload=True):
    """
    Handler for album downloads (the only supported type).
    """
    client = user['highresaudio_api']
    
    try:
        # 'album_url' is the full store URL
        album_meta = await process_album_metadata(album_url, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album HighResAudio: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # Paksa semaphore ke 1 untuk progres
    sem = asyncio.Semaphore(1) 
    
    total_tracks = len(album_meta['tracks'])
    completed_count = 0
    
    async def run_task_with_limit(task_coro, track_meta):
        nonlocal completed_count
        async with sem:
            result = await task_coro
            completed_count += 1
            
            if completed_count % 1 == 0 or completed_count == total_tracks:
                try:
                    # --- PERBAIKAN: Meniru format 5-argumen dari utils.py ---
                    
                    # 1. Buat persentase & bar (logika dari utils.py)
                    percentage_int = int((completed_count/total_tracks)*100)
                    bar = "{0}{1}".format(
                        ''.join(["▰" for _ in range(math.floor(percentage_int / 10))]),
                        ''.join(["▱" for _ in range(10 - math.floor(percentage_int / 10))])
                    )
                    
                    # 2. Panggil edit_message dengan 5 argumen yang benar
                    await edit_message(
                        user['bot_msg'],
                        lang.s.DOWNLOAD_PROGRESS.format(
                            bar,                 # {0}
                            completed_count,     # {1}
                            total_tracks,        # {2}
                            album_meta['title'], # {3}
                            "Tracks"             # {4} (Tipe, seperti di utils.py)
                        )
                    )
                    # --- BATAS PERBAIKAN ---
                except Exception as e:
                    # Log jika masih gagal
                    LOGGER.warning(f"HighResAudio: Gagal mengedit pesan progres: {e}")
            
            return result, track_meta

    task_coroutines = []
    for track in album_meta['tracks']:
        # item_id is not used, track_meta is pre-filled
        task_coro = start_track(None, user, track, False, album_folder) 
        task_coroutines.append(run_task_with_limit(task_coro, track))

    task_results_with_meta = await asyncio.gather(*task_coroutines)
    
    # Filter results
    successful_tracks = []
    for result, track_meta in task_results_with_meta:
        if result: # 'result' is the boolean True/False from start_track
            successful_tracks.append(track_meta)
            
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu HighResAudio yang berhasil diunduh untuk album {album_meta['title']}.")

    # Download Booklet (if exists)
    if 'booklet_url' in album_meta:
        LOGGER.info("HighResAudio: Mengunduh booklet...")
        booklet_path = os.path.join(album_folder, "booklet.pdf")
        booklet_path = sanitize_filepath(booklet_path)
        await asyncio.to_thread(
            download_booklet,
            client,
            album_meta['booklet_url'],
            booklet_path
        )

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
