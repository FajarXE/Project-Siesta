# [GANTI SELURUH FILE: bot/helpers/beatsource/handler.py]

import aiohttp
import aiofiles
import os
import shutil
import traceback
import asyncio 
import random 
import math

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata, 
    process_playlist_metadata,
    custom_url_parse
)
from .api import BeatsourceError, USER_AGENT # Import USER_AGENT
from .manager import beatsource_manager # Import manager untuk refresh link

from ..utils import *

try:
    from ..uploder import *
except ImportError as e:
    raise ImportError(f"Gagal mengimpor uploder.py: {e}")

from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings
from ...settings import bot_set 

import bot.helpers.translations as lang
from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

# --- KONFIGURASI KEAMANAN ---
BEATSOURCE_SEMAPHORE = asyncio.Semaphore(2)

# --- HELPER PROGRESS BAR ---
def make_progress_bar(current, total):
    if total == 0: return "▱" * 10
    percentage = current / total
    finished_length = int(percentage * 10)
    prog_str = "▰" * finished_length + "▱" * (10 - finished_length)
    return prog_str

async def update_progress_msg(msg, current, total, title, media_type):
    try:
        bar = make_progress_bar(current, total)
        formatted_text = lang.s.DOWNLOAD_PROGRESS.format(
            bar, current, total, title, media_type
        )
        await edit_message(msg, formatted_text)
    except Exception as e:
        LOGGER.debug(f"Gagal update pesan progress: {e}")

async def refresh_track_url(item_id: str, current_meta: dict):
    """
    Fungsi darurat: Meminta URL baru ke API jika URL lama expired (403).
    Menggunakan akun dari manager secara acak/tersedia.
    """
    try:
        # Mapping kualitas Metadata -> API Key
        # Metadata: "FLAC" -> API: "lossless"
        # Metadata: "AAC 256" -> API: "high"
        quality_map = {
            "FLAC": "lossless",
            "AAC 256": "high",
            "AAC 128": "medium"
        }
        
        display_quality = current_meta.get('quality', 'AAC 256')
        api_quality = quality_map.get(display_quality, "high")

        LOGGER.info(f"Beatsource: Refreshing URL for track {item_id} ({api_quality})...")
        
        # Ambil daftar klien yang aktif dari manager
        clients = list(beatsource_manager.clients)
        random.shuffle(clients) # Acak agar load balancing tetap jalan
        
        for client in clients:
            try:
                # Coba minta link download baru
                stream_data = await client.get_track_download(item_id, api_quality)
                new_url = stream_data.get("location")
                if new_url:
                    return new_url
            except Exception:
                continue
        
        return None
    except Exception as e:
        LOGGER.error(f"Gagal refresh URL track Beatsource {item_id}: {e}")
        return None

# ----------------------------

async def start_beatsource(url: str, user: dict):
    """Handler utama untuk link Beatsource."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)

        if media_type == 'artist':
            raise NotImplementedError("Unduhan Artis Beatsource belum didukung.")
        
        elif media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        elif media_type == 'album':
            await start_album(item_id, user)
        
        elif media_type == 'playlist':
            await start_playlist(item_id, user, extra_kwargs)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Beatsource handler: {e}\n{traceback.format_exc()}")
        raise e 


async def download_beatsource_track(url: str, filepath: str):
    """
    Pengunduh HTTP async dengan Header Browser & Deteksi 403.
    """
    try:
        # Header lengkap agar tidak dianggap bot
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": "https://www.beatsource.com/"
        }

        # Timeout 10 menit
        timeout = aiohttp.ClientTimeout(total=600)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            async with session.get(url) as response:
                # Tangkap 403 (Forbidden/Expired) secara spesifik
                if response.status == 403:
                    return "403_FORBIDDEN"

                response.raise_for_status()
                
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)
        return None 
    except Exception as e:
        return f"Gagal mengunduh file: {e}"


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    async with BEATSOURCE_SEMAPHORE:
        delay = random.uniform(3.0, 6.0)
        await asyncio.sleep(delay)
        
        if not track_meta:
            try:
                track_meta = await process_track_metadata(item_id, user['r_id'], user)
            except Exception as e:
                LOGGER.warning(f"Beatsource track {item_id} tidak tersedia: {e}")
                return False
                
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
            filepath = sanitize_filepath(filepath)

        download_url = track_meta.get('download_url')
        if not download_url:
            LOGGER.error(f"Tidak ada URL download ditemukan untuk track Beatsource {item_id}")
            return False

        track_meta['folderpath'] = filepath
        
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        safe_filename = sanitize_filepath(raw_filename)

        filepath += f"/{safe_filename}.{track_meta['extension']}"
        track_meta['filepath'] = filepath

        # --- DOWNLOAD PERTAMA ---
        err = await download_beatsource_track(download_url, track_meta['filepath'])

        # --- LOGIKA RETRY (AUTO REFRESH URL) ---
        if err == "403_FORBIDDEN":
            LOGGER.warning(f"URL Beatsource Track {item_id} expired (403). Mencoba refresh URL...")
            
            # Minta URL baru
            new_url = await refresh_track_url(item_id, track_meta)
            
            if new_url:
                track_meta['download_url'] = new_url # Update di memori
                # Coba download lagi
                err = await download_beatsource_track(new_url, track_meta['filepath'])
            else:
                err = "Gagal refresh URL Beatsource (tetap 403/Error API)."

        if err:
            LOGGER.error(f"Beatsource dl_track gagal untuk {item_id}: {err}")
            return False

        try:
            await set_metadata(track_meta, user['user_id'])
        except FileNotFoundError:
            LOGGER.error(f"File hilang setelah download: {filepath}")
            return False
        except Exception as e:
            LOGGER.error(f"Gagal memproses metadata Beatsource: {filepath} -> {e}")
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
        raise Exception(f"Gagal mendapatkan metadata album Beatsource: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    total = len(album_meta['tracks'])
    successful_tracks = []

    await update_progress_msg(user['bot_msg'], 0, total, album_meta['title'], album_meta['type'])

    for i, track in enumerate(album_meta['tracks']):
        # URL mungkin expired, start_track akan handle
        success = await start_track(track['itemid'], user, track, False, album_folder)
        
        if success:
            successful_tracks.append(track)
            
        await update_progress_msg(user['bot_msg'], i + 1, total, album_meta['title'], album_meta['type'])

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Beatsource yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        try:
            cover_src = album_meta.get('cover')
            if cover_src:
                target_cover = os.path.join(album_meta['folderpath'], "cover.jpg")
                if os.path.exists(cover_src):
                    shutil.copy(cover_src, target_cover)
                elif cover_src.startswith('http'):
                    await download_beatsource_track(cover_src, target_cover)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ZIP: {e}")

        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_playlist(playlist_id: str, user: dict, extra: dict, upload=True):
    try:
        play_meta = await process_playlist_metadata(playlist_id, user['r_id'], user, extra)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata playlist Beatsource: {e}")

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/{play_meta['title']}"
    playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder

    if upload:
        play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    total = len(play_meta['tracks'])
    successful_tracks = []

    await update_progress_msg(user['bot_msg'], 0, total, play_meta['title'], play_meta['type'])

    for i, track in enumerate(play_meta['tracks']):
        # Start_track akan otomatis refresh URL jika kena 403
        success = await start_track(track['itemid'], user, track, False, playlist_folder)
        if success:
            successful_tracks.append(track)
        
        await update_progress_msg(user['bot_msg'], i + 1, total, play_meta['title'], play_meta['type'])

    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Beatsource yang berhasil diunduh untuk playlist {play_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        try:
            cover_src = play_meta.get('cover')
            if cover_src:
                target_cover = os.path.join(play_meta['folderpath'], "cover.jpg")
                if os.path.exists(cover_src):
                    shutil.copy(cover_src, target_cover)
                elif cover_src.startswith('http'):
                    await download_beatsource_track(cover_src, target_cover)
        except: pass

        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
