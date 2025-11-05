# [FILE BARU: bot/helpers/kkbox/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    # process_album_metadata, 
    # process_playlist_metadata,
    custom_url_parse
)
from .manager import KKBoxError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks
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
        
        # elif media_type == 'album':
        #     await start_album(item_id, user)
        
        # elif media_type == 'playlist':
        #     await start_playlist(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media KKBox '{media_type}' belum didukung.")
        
        await edit_message(user['bot_msg'], lang.s.TASK_COMPLETED)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di KKBox handler: {e}\n{traceback.format_exc()}")
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
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata KKBox: {filepath} -> {e}")
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True

# ... (Implementasikan start_album / start_playlist nanti) ...
