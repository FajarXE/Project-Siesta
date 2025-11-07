# [FILE BARU: bot/helpers/soundcloud/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config
from bot.logger import LOGGER

# Impor API dan manager
from .api import SoundcloudError
from .manager import soundcloud_manager

# Impor fungsi metadata yang baru kita buat
from .metadata import (
    process_track_metadata, 
    process_playlist_or_album,
    custom_url_parse
)

# Impor utilitas bot yang sudah ada
from ..utils import *
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings
from ...settings import bot_set
import bot.helpers.translations as lang


async def download_soundcloud_track(download_url: str, download_type: str, filepath: str):
    """
    Pengunduh file Soundcloud.
    Menangani 3 kasus:
    1. 'original': File asli (wav, flac, mp3) -> Unduh langsung.
    2. 'progressive': Stream MP3/OGG -> Unduh langsung.
    3. 'hls': Stream M3U8 (AAC) -> Gunakan ffmpeg.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        if download_type == 'original' or download_type == 'progressive':
            # Ini adalah URL unduhan langsung
            LOGGER.debug(f"Soundcloud: Mengunduh (progresif/asli) dari {download_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    response.raise_for_status()
                    async with aiofiles.open(filepath, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
            return None # Sukses

        elif download_type == 'hls':
            # Ini adalah stream M3U8, perlu ffmpeg
            # Logika dari interface.py: '-c copy' dan '-bsf:a aac_adtstoasc'
            LOGGER.debug(f"Soundcloud: Menggunakan ffmpeg (HLS) untuk {download_url}")
            
            args = [
                'ffmpeg',
                '-y',               # Timpa file output jika ada
                '-i', download_url,   # Input: URL m3u8
                '-c', 'copy',       # Salin codec (tidak re-encode)
                '-bsf:a', 'aac_adtstoasc', # Perbaikan untuk stream AAC
                filepath            # File output (harus .m4a)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode()
                LOGGER.error(f"Soundcloud: ffmpeg gagal!\n{error_msg}")
                # Hapus file yang mungkin rusak
                if os.path.exists(filepath):
                    os.remove(filepath)
                return f"ffmpeg gagal: {error_msg}"
            
            LOGGER.debug("Soundcloud: ffmpeg HLS berhasil digabungkan.")
            return None # Sukses

        else:
            return f"Tipe unduhan tidak dikenal: {download_type}"
            
    except Exception as e:
        return f"Gagal mengunduh file: {e}"


async def start_track(item_id: str, user: dict, pre_data: dict = None, upload=True, \
    filepath=None, disable_link=False):
    """Memulai alur kerja untuk satu track Soundcloud."""
    
    track_meta = None
    try:
        if not pre_data: # pre_data hanya ada jika dipanggil dari album/playlist
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        else:
            track_meta = pre_data # pre_data SUDAH track_meta lengkap dari process_playlist
            
        if not filepath:
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album'] or track_meta['title']}"
            filepath = sanitize_filepath(filepath)
    except Exception as e:
        LOGGER.warning(f"Soundcloud track {item_id} tidak tersedia: {e}")
        return False
            
    download_url = track_meta.get('download_url')
    download_type = track_meta.get('download_type')
    if not download_url or not download_type:
        LOGGER.error(f"Tidak ada URL/Tipe download ditemukan untuk track SC {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # Memanggil pengunduh HTTP/FFMPEG kita
    err = await download_soundcloud_track(
        download_url, 
        download_type, 
        track_meta['filepath']
    )
    if err:
        LOGGER.error(f"Soundcloud dl_track gagal untuk {item_id}: {err}")
        return False

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download SC: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata SC: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album_or_playlist(item_id: str, user: dict, pre_data: dict, media_type: str, upload=True):
    """Memulai alur kerja untuk album atau playlist Soundcloud."""
    try:
        # 'pre_data' dari resolve sudah ada, tapi kita proses lagi untuk dapat list track
        multi_meta = await process_playlist_or_album(
            item_id, 
            user['r_id'], 
            user, 
            pre_data, 
            media_type
        )
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata {media_type} SC: {e}")

    folder_name = multi_meta['albumartist'] if media_type == 'album' else multi_meta['title']
    item_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{multi_meta['provider']}/{folder_name}"
    
    item_folder = sanitize_filepath(item_folder)
    multi_meta['folderpath'] = item_folder

    if upload:
        multi_meta['poster_msg'] = await post_art_poster(user, multi_meta)

    tasks = []
    # 'multi_meta['tracks']' sudah berisi metadata track LENGKAP
    for track_meta in multi_meta['tracks']:
        tasks.append(start_track(
            track_meta['itemid'], 
            user, 
            track_meta, # Berikan metadata yang sudah diproses
            False, # Jangan upload satu per satu
            item_folder
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': multi_meta['title'],
        'type': multi_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [multi_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    multi_meta['tracks'] = successful_tracks
    multi_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu SC yang berhasil diunduh untuk {multi_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    is_zip = (media_type == 'album' and album_zip) or (media_type == 'playlist' and playlist_zip)

    if is_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {multi_meta['totaltracks']} lagu menjadi .zip...")
        multi_meta['zip_path'] = await zip_handler(multi_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        if media_type == 'album':
            await album_upload(multi_meta, user)
        else:
            await playlist_upload(multi_meta, user)


async def start_soundcloud(link: str, user: dict):
    """Handler utama untuk link Soundcloud."""
    
    client = soundcloud_manager.get_client()
    if not client:
        raise SoundcloudError("Modul Soundcloud tidak diinisialisasi (Token hilang atau salah).")
        
    user['soundcloud_api'] = client
    
    try:
        # custom_url_parse Soundcloud bersifat async dan memanggil 'resolve'
        media_type, item_id, extra = await custom_url_parse(link, client)

        if media_type == 'artist':
            raise NotImplementedError("Unduhan Artis Soundcloud (semua track) belum didukung.")
        
        elif media_type == 'track':
            # 'extra' berisi 'pre_data' dari resolve
            await start_track(item_id, user, extra.get('pre_data'))
        
        elif media_type == 'album' or media_type == 'playlist':
            await start_album_or_playlist(item_id, user, extra.get('pre_data'), media_type)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Soundcloud handler: {e}\n{traceback.format_exc()}")
        raise e 
