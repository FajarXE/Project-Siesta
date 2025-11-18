# [GANTI FILE: bot/helpers/kkbox/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata, # --- DITAMBAHKAN ---
    # process_playlist_metadata,
    custom_url_parse
)
from .manager import KKBoxError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
# --- PERBAIKAN: Impor zip_handler dan format_string ---
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler
# --- AKHIR PERBAIKAN ---
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

async def start_kkbox(url: str, user: dict):
    """Handler utama untuk link KKBox."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        # --- MODIFIKASI DIMULAI ---
        elif media_type == 'album':
            await start_album(item_id, user)
        # --- MODIFIKASI SELESAI ---
            
        # elif media_type == 'playlist':
            # raise NotImplementedError(f"Tipe media KKBox '{media_type}' belum didukung.")
            
        else:
            raise NotImplementedError(f"Tipe media KKBox '{media_type}' belum didukung.")
        
        # --- PERBAIKAN: Hapus 'TASK_COMPLETED' agar tidak menimpa status akhir ---
        # await edit_message(user['bot_msg'], lang.s.TASK_COMPLETED)
        # --- AKHIR PERBAIKAN ---
        
    except Exception as e:
        LOGGER.error(f"Error fatal di KKBox handler: {e}\n{traceback.format_exc()}")
        # Melempar error agar download.py tahu tugasnya gagal
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    client = user['kkbox_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"KKBox track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    download_id = track_meta.get('download_id')
    download_quality = track_meta.get('download_quality_key')
    if not download_id or not download_quality:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan KKBox track {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- LOGIKA UNDUH KKBox ---
    try:
        # Tentukan format berdasarkan kualitas
        format_key = {
            '128k': 'mp3_128k_chromecast',
            '192k': 'mp3_192k_kkdrm1',
            '320k': 'aac_320k_m4a_kkdrm1',
            'hifi': 'flac_16_download_kkdrm',
            'hires': 'flac_24_download_kkdrm',
        }[download_quality]
        
        play_mode = 'chromecast' if format_key == 'mp3_128k_chromecast' else None

        # 1. Dapatkan Tiket (Async)
        urls_list = await asyncio.to_thread(client.get_ticket, download_id, play_mode)
        
        download_url = None
        for fmt in urls_list:
            if fmt['name'] == format_key:
                download_url = fmt['url']
                break
        
        if not download_url:
            raise KKBoxError(f"Format {format_key} tidak ditemukan di tiket.")
            
        # Pastikan direktori ada
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 2. Unduh & Dekripsi (Async)
        if format_key == 'mp3_128k_chromecast':
            # Ini adalah unduhan HTTP sederhana (tanpa DRM)
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    response.raise_for_status()
                    async with aiofiles.open(track_meta['filepath'], "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
        else:
            # Ini adalah unduhan terenkripsi, jalankan di thread
            await asyncio.to_thread(
                client.kkdrm_dl,
                download_url,
                track_meta['filepath']
            )

    except Exception as e:
        LOGGER.error(f"KKBox dl_track gagal untuk {item_id}: {e}")
        return False
    # --- BATAS LOGIKA UNDUH ---

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download KKBox: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata KKBox: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True

# --- FUNGSI BARU ---
async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album (didasarkan pada handler.py Beatport)
    """
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album KKBox: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder # Path direktori asli (string)

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
        raise Exception(f"Tidak ada lagu KKBox yang berhasil diunduh untuk album {album_meta['title']}.")

    # --- PERBAIKAN: Unpack 4 nilai (urutan baru) ---
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        # --- PERBAIKAN: Gunakan 'zip_path' agar konsisten ---
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
# --- BATAS FUNGSI BARU ---
