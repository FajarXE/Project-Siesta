# [TARUH DI: bot/helpers/nugs/handler.py]

import asyncio
import os
import re
import traceback
import aiohttp
import aiofiles

from pathvalidate import sanitize_filepath
from config import Config

# Impor dari modul Nugs Anda
from .nugs_api import NugsNotAvailableError
from .mqa_identifier import MqaIdentifier
from .utils import create_temp_filename

# Impor yang diperlukan dari bot
from ..uploder import *
from ..metadata import set_metadata, create_cover_file
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string
from bot.logger import LOGGER
import bot.helpers.translations as lang

# Prioritas Kualitas (didasarkan pada interface.py)
# Format: {codec_enum: (nama_kualitas, ekstensi, prioritas)}
QUALITY_MAP = {
    'AAC': ("AAC 150k", "m4a", 0),
    'ALAC': ("ALAC 16-bit", "m4a", 1), # ALAC menggunakan ekstensi .m4a
    'FLAC': ("FLAC 16-bit", "flac", 2),
    'MQA': ("MQA", "flac", 3), # Akan diupdate oleh detektor MQA
    'MHA1': ("Sony 360RA", "m4a", 4) # (Format Spasial)
}

# Regex dari interface.py
URL_REGEX = r'https?://play.nugs.net/#/(artist|catalog/recording|playlists/playlist)/(\d+)'

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Nugs."""
    match = re.search(URL_REGEX, link)
    if not match:
        raise Exception(f"URL Nugs tidak valid: {link}")
    
    media_type_raw = match.group(1)
    item_id = match.group(2)
    
    media_types = {
        'catalog/recording': 'album',
        'artist': 'artist',
        'playlists/playlist': 'playlist',
    }
    
    media_type = media_types.get(media_type_raw)
    if not media_type:
         raise NotImplementedError(f"Tipe media Nugs '{media_type_raw}' belum didukung.")
         
    return media_type, item_id

async def parse_stream_format(stream_url: str):
    """Mengurai URL stream untuk menentukan kualitas (dari interface.py)"""
    #
    if ".aac150/" in stream_url: return 'AAC'
    if ".alac16/" in stream_url: return 'ALAC'
    if ".flac16/" in stream_url: return 'FLAC'
    if ".mqa24/" in stream_url: return 'MQA'
    if ".s360/" in stream_url: return 'MHA1'
    return None

async def download_temp_header(file_url: str, user_agent: str) -> str | None:
    """Mengunduh header file untuk analisis MQA (dari interface.py)"""
    #
    temp_location = await asyncio.to_thread(create_temp_filename, '.flac')
    
    try:
        headers = {'User-Agent': user_agent, 'Range': 'bytes=0-32768'}
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url, headers=headers) as response:
                response.raise_for_status()
                async with aiofiles.open(temp_location, 'wb') as f:
                    await f.write(await response.content.read())
        return temp_location
    except Exception as e:
        LOGGER.warning(f"Nugs: Gagal mengunduh header MQA: {e}")
        if os.path.exists(temp_location):
            os.remove(temp_location)
        return None

async def process_track_metadata(track_data: dict, album_data: dict, user: dict):
    """Memproses metadata untuk satu lagu (logika dari interface.py)"""
    #
    
    client = user['nugs_api'] # Ini adalah instance NugsApi
    sub_details = client.subscription_details # Diatur oleh manager.py
    
    metadata = {
        'provider': 'Nugs.net',
        'type': 'track',
        'itemid': track_data.get('songID'),
        'title': track_data.get('songTitle'),
        'artist': album_data.get('artistName'),
        'albumartist': album_data.get('artistName'),
        'album': album_data.get('containerInfo'),
        'tracknumber': str(track_data.get('trackNum')),
        'totaltracks': str(len(album_data.get('songs'))),
        'discnumber': str(track_data.get('discNum')),
        'totaldiscs': str(album_data.get('numDiscs', 1)),
        'date': album_data.get('releaseDateFormatted', '').replace('/', '-'),
        'copyright': f"© {album_data.get('releaseDateFormatted', '')[:4]} {album_data.get('licensorName')}",
        'explicit': False, # Nugs tampaknya tidak menandai ini
        'isrc': None, # Tidak tersedia di API
    }
    
    # Sampul
    cover_url = f"https://secure.livedownloads.com{album_data.get('img', {}).get('url')}"
    metadata['cover'] = await create_cover_file(cover_url, metadata)
    metadata['thumbnail'] = await create_cover_file(cover_url.replace('.jpg', '_small.jpg'), metadata, True)

    # --- Logika Kualitas (dari interface.py) ---
    stream_data = []
    #
    for stream_format_id in [9, 5, 2, None]: # Prioritas Nugs: MQA, FLAC, ALAC, AAC
        try:
            stream_info = await asyncio.to_thread(
                client.get_stream,
                track_data.get('trackID'),
                sub_details,
                stream_format_id
            )
            stream_url = stream_info.get('streamLink')
            codec_key = await parse_stream_format(stream_url)
            
            if codec_key:
                quality_name, extension, priority = QUALITY_MAP[codec_key]
                stream_data.append({
                    'url': stream_url,
                    'codec': codec_key,
                    'quality_name': quality_name,
                    'extension': extension,
                    'priority': priority
                })
        except Exception as e:
            LOGGER.debug(f"Nugs: Gagal mendapatkan stream format {stream_format_id}: {e}")
            continue
            
    if not stream_data:
        raise NugsError(f"Tidak ada stream yang valid ditemukan untuk track {metadata['title']}")
        
    # Urutkan berdasarkan prioritas (tertinggi dulu)
    stream_data = sorted(stream_data, key=lambda k: k['priority'], reverse=True)
    selected_stream = stream_data[0] # Ambil kualitas terbaik yang tersedia
    
    metadata['quality'] = selected_stream['quality_name']
    metadata['extension'] = selected_stream['extension']
    metadata['download_url'] = selected_stream['url']
    
    # --- Deteksi MQA ---
    #
    if selected_stream['codec'] == 'MQA':
        LOGGER.debug(f"Nugs: Deteksi MQA untuk {metadata['title']}...")
        temp_flac_header = await download_temp_header(selected_stream['url'], client.session.user_agent)
        
        if temp_flac_header:
            try:
                mqa_file = await asyncio.to_thread(MqaIdentifier, temp_flac_header)
                if mqa_file.is_mqa:
                    original_rate = mqa_file.get_original_sample_rate()
                    studio = " Studio" if mqa_file.is_mqa_studio else ""
                    metadata['quality'] = f"MQA{studio} {mqa_file.bit_depth}-bit / {original_rate}kHz"
                    metadata['bit_depth'] = mqa_file.bit_depth
                    metadata['sample_rate'] = mqa_file.original_sample_rate
                    LOGGER.info(f"Nugs: Deteksi MQA Berhasil: {metadata['quality']}")
                else:
                    LOGGER.warning(f"Nugs: File ditandai MQA tetapi detektor gagal memverifikasi.")
                    metadata['quality'] = "FLAC 24-bit" # Fallback jika MQA tapi gagal deteksi
                    metadata['bit_depth'] = 24
                    
            except Exception as e:
                LOGGER.error(f"Nugs: Error MqaIdentifier: {e}")
            finally:
                if os.path.exists(temp_flac_header):
                    os.remove(temp_flac_header)
        else:
             LOGGER.warning(f"Nugs: Gagal mengunduh header MQA untuk analisis.")

    elif selected_stream['codec'] in ['FLAC', 'ALAC']:
        metadata['bit_depth'] = 16
        metadata['sample_rate'] = 44100
    
    return metadata

async def start_track(track_meta: dict, user: dict, upload=True):
    """Handler untuk mengunduh satu track Nugs (mirip dengan KKBox)"""
    
    client = user['nugs_api']
    filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
    filepath = sanitize_filepath(filepath)
    
    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- Logika Unduh ---
    try:
        download_url = track_meta['download_url']
        user_agent = client.session.user_agent
        
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Ini adalah unduhan HTTP sederhana
        async with aiohttp.ClientSession() as session:
            async with session.get(download_url, headers={'User-Agent': user_agent}) as response:
                response.raise_for_status()
                async with aiofiles.open(track_meta['filepath'], "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        await f.write(chunk)

    except Exception as e:
        LOGGER.error(f"Nugs dl_track gagal untuk {track_meta['itemid']}: {e}")
        return False
    # --- Batas Logika Unduh ---

    try:
        await set_metadata(track_meta)
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Nugs: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user)

    return True

async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album Nugs.
    """
    client = user['nugs_api']
    
    try:
        # Panggil API di thread terpisah (karena 'requests' blocking)
        album_data = await asyncio.to_thread(client.get_album, album_id)
        if not album_data:
            raise NugsError(f"Album {album_id} tidak ditemukan.")
            
        tracks_list = album_data.get('songs', [])
        
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Nugs: {e}")

    # Proses metadata album dasar
    album_meta = {
        'provider': 'Nugs.net',
        'type': 'album',
        'itemid': album_id,
        'title': album_data.get('containerInfo'),
        'artist': album_data.get('artistName'),
        'albumartist': album_data.get('artistName'),
        'date': album_data.get('releaseDateFormatted', '').replace('/', '-'),
        'totaltracks': str(len(tracks_list))
    }
    
    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        # Dapatkan sampul untuk poster
        cover_url = f"https://secure.livedownloads.com{album_data.get('img', {}).get('url')}"
        album_meta['cover'] = await create_cover_file(cover_url, album_meta)
        album_meta['thumbnail'] = await create_cover_file(cover_url.replace('.jpg', '_small.jpg'), album_meta, True)
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track_data in tracks_list:
        try:
            # Kirim track_data dan album_data agar tidak perlu fetch ulang
            track_meta = await process_track_metadata(track_data, album_data, user)
            tasks.append(start_track(track_meta, user, False)) # Upload=False
        except Exception as e:
            LOGGER.warning(f"Nugs: Gagal memproses track {track_data.get('songID')} di album: {e}")
            continue

    if not tasks:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album Nugs {album_meta['title']}")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks_count = sum(1 for result in task_results if result)

    if successful_tracks_count == 0:
        raise Exception(f"Tidak ada lagu Nugs yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {successful_tracks_count} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)

async def start_nugs(url: str, user: dict):
    """Handler utama untuk link Nugs."""
    try:
        media_type, item_id = custom_url_parse(url)
        
        if media_type == 'album':
            await start_album(item_id, user)
        
        elif media_type == 'artist':
            raise NotImplementedError(f"Tipe media Nugs '{media_type}' (Artist) belum didukung.")
        
        elif media_type == 'playlist':
            raise NotImplementedError(f"Tipe media Nugs '{media_type}' (Playlist) belum didukung.")
            
        else:
            raise NotImplementedError(f"Tipe media Nugs '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Nugs handler: {e}\n{traceback.format_exc()}")
        raise e # Melempar error agar download.py tahu tugasnya gagal
