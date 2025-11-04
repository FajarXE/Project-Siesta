# [GANTI SELURUH FILE: bot/helpers/beatport/handler.py]

import aiohttp
import aiofiles
import os
import traceback

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata, 
    process_playlist_metadata,
    custom_url_parse
)
from .api import BeatportError

from ..utils import *
# Baris 'from ..uploader import *' yang salah telah dihapus

from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings

# --- PERBAIKAN DI SINI ---
from ...settings import bot_set # '..' diubah kembali menjadi '...' (tiga titik)
# --- PERBAIKAN SELESAI ---

import bot.helpers.translations as lang
from bot.logger import LOGGER

async def start_beatport(url: str, user: dict):
    """Handler utama untuk link Beatport."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)

        if media_type == 'artist':
            # (Belum didukung oleh file Anda, bisa ditambahkan nanti)
            raise NotImplementedError("Unduhan Artis Beatport belum didukung.")
        
        elif media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        elif media_type == 'album':
            await start_album(item_id, user)
        
        elif media_type == 'playlist':
            await start_playlist(item_id, user, extra_kwargs)
        
        await edit_message(user['bot_msg'], lang.s.TASK_COMPLETED)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Beatport handler: {e}\n{traceback.format_exc()}")
        await edit_message(user['bot_msg'], f"Error Beatport: {e}")


async def download_beatport_track(url: str, filepath: str):
    """Pengunduh HTTP async sederhana untuk file Beatport (MP4/FLAC)."""
    try:
        # Kita perlu sesi baru karena API menggunakan sesi terpisah
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
        return None # Sukses
    except Exception as e:
        return f"Gagal mengunduh file: {e}"


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"Beatport track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    download_url = track_meta.get('download_url')
    if not download_url:
        LOGGER.error(f"Tidak ada URL download ditemukan untuk track Beatport {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # Memanggil pengunduh HTTP sederhana kita
    err = await download_beatport_track(download_url, track_meta['filepath'])
    if err:
        LOGGER.error(f"Beatport dl_track gagal untuk {item_id}: {err}")
        return False

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Beatport: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Beatport: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album(album_id: str, user: dict, upload=True):
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Beatport: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
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
        raise Exception(f"Tidak ada lagu Beatport yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['folderpath'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_playlist(playlist_id: str, user: dict, extra: dict, upload=True):
    try:
        play_meta = await process_playlist_metadata(playlist_id, user['r_id'], user, extra)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata playlist Beatport: {e}")

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/{play_meta['title']}"
    playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder

    if upload:
        play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    tasks = []
    for track in play_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)

    successful_tracks = [play_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Beatport yang berhasil diunduh untuk playlist {play_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        play_meta['folderpath'] = await zip_handler(play_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
