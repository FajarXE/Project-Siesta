# [GANTI FILE: bot/helpers/highresaudio/metadata.py]

import copy
import re
import asyncio
import traceback 
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import highresaudio_manager, HighResAudioError
from bot.logger import LOGGER

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL HighResAudio."""
    
    # Regex dari HRA-DL.py
    pattern = r"https?://(?:www\.)?highresaudio\.com/[a-z]{2}/album/view/(\w+)/.*"
    match = re.match(pattern, link)
    
    if match:
        # Skrip HRA-DL hanya mendukung album.
        # Kita teruskan seluruh URL sebagai 'item_id' untuk diproses oleh metadata.
        return 'album', link, {}
    else:
        raise HighResAudioError('URL HighResAudio tidak valid atau tidak didukung.')


async def _process_cover(metadata: dict, url: str):
    """Memproses sampul dari URL (jika ditemukan)."""
    # create_cover_file mengharapkan URL string, atau None
    if not url:
        LOGGER.warning("HighResAudio: Tidak ada URL sampul valid yang ditemukan.")
        return metadata['tempfolder'] + "cover.jpg" # Fallback
    return await create_cover_file(url, metadata)


async def process_album_metadata(album_url: str, r_id: str, user: dict):
    """
    Memproses metadata untuk satu album.
    Ini melakukan proses 2 langkah: scrape ID, lalu panggil API.
    """
    client = user['highresaudio_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        # LANGKAH 1: Scrape halaman HTML untuk mendapatkan ID internal
        LOGGER.debug(f"HighResAudio: Scraping ID dari {album_url}")
        album_id = await asyncio.to_thread(
            client.get_album_id_from_url, 
            album_url
        )
        LOGGER.debug(f"HighResAudio: Mendapatkan album_id internal: {album_id}")

        # LANGKAH 2: Panggil API menggunakan ID internal
        api_data = await asyncio.to_thread(
            client.get_album_metadata, 
            album_id
        )
        
        data = api_data.get('data', {}).get('results', {})
        if not data:
            raise HighResAudioError("Respons API tidak berisi data 'results'.")

    except Exception as e:
        LOGGER.error(f"HighResAudio: Gagal mendapatkan metadata album: {e}\n{traceback.format_exc()}")
        raise e

    # Memetakan Metadata Album
    metadata['itemid'] = album_id
    metadata['title'] = data.get('title')
    metadata['album'] = data.get('title')
    metadata['artist'] = data.get('artist')
    metadata['albumartist'] = data.get('artist')
    metadata['provider'] = 'HighResAudio'
    metadata['type'] = 'album'
    
    track_list = data.get('tracks', [])
    metadata['totaltracks'] = str(len(track_list))
    
    # --- PERBAIKAN: Gunakan '' (string kosong) untuk DATE, dan 1/False untuk sisanya ---
    # 1. RELEASE DATE: Gunakan fallback '' (string kosong).
    release_date_raw = data.get('publishDate', '') 
    metadata['date'] = release_date_raw[:4] # Jika '' maka akan jadi ''
    
    # 2. TOTAL VOLUMES: Gunakan fallback 1 (ini sudah berfungsi)
    total_volumes = data.get('discCount', 1) 
    metadata['totalvolumes'] = str(total_volumes)
    
    # 3. EXPLICIT: Gunakan fallback False (ini sudah berfungsi)
    metadata['explicit'] = bool(data.get('explicit', False))
    # --- BATAS PERBAIKAN ---

    # --- Logika Sampul (Cover) ---
    cover_url_str = None
    try:
        cover_data = data.get('cover') 
        if isinstance(cover_data, dict):
            file_url = cover_data.get('master', {}).get('file_url')
            if file_url:
                cover_url_str = f"https://{file_url}"
                LOGGER.debug(f"HighResAudio: Menemukan URL sampul: {cover_url_str}")
        elif isinstance(cover_data, str):
            cover_url_str = cover_data
    except Exception as e:
        LOGGER.warning(f"HighResAudio: Gagal mem-parsing struktur data sampul: {e}")
        pass 

    metadata['cover'] = await _process_cover(metadata, cover_url_str)
    metadata['thumbnail'] = metadata['cover']
    # --- BATAS PERBAIKAN ---

    # Memetakan Metadata Lagu
    metadata['tracks'] = []
    for track in track_list:
        try:
            track_meta = copy.deepcopy(base_meta)
            track_meta['tempfolder'] = metadata['tempfolder']
            
            # Salin metadata album
            track_meta['title'] = track.get('title')
            track_meta['album'] = metadata['album']
            track_meta['artist'] = metadata['artist']
            track_meta['albumartist'] = metadata['albumartist']
            track_meta['provider'] = 'HighResAudio'
            track_meta['type'] = 'track'
            track_meta['cover'] = metadata['cover']
            track_meta['thumbnail'] = metadata['thumbnail']
            # --- PERBAIKAN: Salin data baru ke metadata lagu ---
            track_meta['date'] = metadata['date'] # Ini akan menyalin '' jika tidak ada
            track_meta['explicit'] = metadata['explicit']
            # --- BATAS PERBAIKAN ---

            # Metadata spesifik lagu
            track_meta['itemid'] = track.get('id') # Asumsi
            track_meta['tracknumber'] = str(track.get('trackNumber')).zfill(2)
            track_meta['totaltracks'] = metadata['totaltracks']
            
            # --- PERBAIKAN: Gunakan fallback 1 (logika sebelumnya) ---
            disc_num = track.get('discNumber', 1) 
            track_meta['discnumber'] = str(disc_num)
            track_meta['totalvolumes'] = metadata['totalvolumes']
            # --- BATAS PERBAIKAN ---

            # Kualitas & Ekstensi (HRA-DL selalu FLAC)
            track_meta['quality'] = f"{track.get('format')} kHz FLAC"
            track_meta['extension'] = 'flac'
            
            # Info Unduhan Kritis
            track_meta['download_url'] = track.get('url')
            # 'album_id_referer' diperlukan oleh API untuk header Referer
            track_meta['album_id_referer'] = album_id 

            if not track_meta['download_url']:
                raise HighResAudioError(f"Tidak ada URL unduhan untuk track {track_meta['title']}")

            metadata['tracks'].append(track_meta)
            
        except Exception as e:
            LOGGER.error(f"HighResAudio: Gagal memproses track {track.get('title')}: {e}\n{traceback.format_exc()}")
            continue

    # Booklet (dari HRA-DL.py)
    if "booklet" in data and data['booklet']:
        # URL booklet sudah lengkap 'https://...'
        metadata['booklet_url'] = data['booklet']
        LOGGER.info(f"HighResAudio: Menemukan booklet di {data['booklet']}")

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
