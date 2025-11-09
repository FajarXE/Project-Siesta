# [BUAT FILE BARU: bot/helpers/idagio/metadata.py]

import copy
import re
import aiohttp
import asyncio
import os 
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import idagio_manager, IdagioError
from bot.logger import LOGGER

# Pemetaan dari bot Anda ke nilai API Idagio
QUALITY_MAP_API = {
    "FLAC": 90,
    "MP3_320": 70,
    "MP3_160": 50
}
# Pemetaan dari nilai API ke tampilan
QUALITY_MAP_DISPLAY = {
    90: ("FLAC", "flac"),
    70: ("AAC 320k", "m4a"),
    50: ("AAC 160k", "m4a")
}
# Urutan prioritas kualitas
QUALITY_ORDER = ["FLAC", "MP3_320", "MP3_160"]


def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Idagio"""
    link = re.sub(r'/[a-z]{2}/', '/', link) # Hapus kode bahasa
    url = urlparse(link)
    components = url.path.split('/')
    
    if not components or len(components) <= 2:
        raise IdagioError(f'URL tidak valid: {link}')
    
    # Format: /TYPE/ID
    if len(components) in {3, 4}:
        type_ = components[1]
        media_id = components[2]
    else:
        raise IdagioError(f'URL tidak valid: {link}')

    if type_ == 'recordings':
        media_type = 'track'
    elif type_ == 'albums':
        media_type = 'album'
    elif type_ == 'playlists':
        media_type = 'playlist'
    elif type_ == 'profiles':
        media_type = 'artist'
    else:
        raise IdagioError(f'Tipe URL Idagio tidak didukung: {type_}')

    return media_type, media_id, {}


async def _process_cover(metadata: dict, url: str):
    """Memproses sampul dari URL Idagio"""
    return await create_cover_file(url, metadata)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    """Memproses metadata untuk satu lagu (recording)."""
    client = user['idagio_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        if pre_data:
            track_data = pre_data
        else:
            track_data = await asyncio.to_thread(client.get_recording, track_id)
            
        if alb_info_pre:
            album_data = alb_info_pre
        else:
            album_id = track_data.get('albums')[0] # Ambil album pertama
            album_data = await asyncio.to_thread(client.get_album, album_id)

    except Exception as e:
        LOGGER.error(f"Idagio: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    if track_data.get('geoblocked'):
        raise IdagioError(f"Track '{track_data.get('name')}' diblokir di wilayah Anda.")

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('work').get('title') #
    metadata['album'] = album_data.get('title')
    
    # --- Logika Artis & Composer ---
    # Idagio berfokus pada klasik, jadi 'artist' adalah 'performer'
    # dan 'albumartist' & 'composer' adalah 'composer'
    try:
        metadata['composer'] = track_data.get('work').get('composer').get('name')
    except AttributeError:
        LOGGER.warning("Idagio: Gagal mendapatkan composer utama.")
        metadata['composer'] = "Various Artists"

    # Coba temukan 'albumartist' (composer album)
    try:
        album_artist_obj = [c for c in album_data.get('participants') if c.get('type') == 'composer'][0]
        metadata['albumartist'] = album_artist_obj.get('name')
    except (IndexError, AttributeError):
        metadata['albumartist'] = metadata['composer'] # Fallback ke composer track

    # 'artist' adalah ringkasan performer
    metadata['artist'] = track_data.get('summary') #
    # --- Batas Logika Artis ---

    # --- Temukan Track Number ---
    track_number = 1
    download_track_id = None
    try:
        download_track_id = track_data.get('tracks')[0].get('id') # Ini adalah ID untuk stream
        for i, track in enumerate(album_data.get('tracks')):
            if track.get('id') == download_track_id:
                track_number = i + 1
                break
    except (IndexError, AttributeError):
        LOGGER.warning(f"Idagio: Gagal menemukan track number untuk {track_id}")
    
    metadata['tracknumber'] = str(track_number)
    metadata['totaltracks'] = str(len(album_data.get('tracks')))

    metadata['date'] = album_data.get('publishDate', '1900')[:4] #
    metadata['copyright'] = f'©℗ {album_data.get("copyright")}' #
    metadata['upc'] = album_data.get('upc')
    metadata['provider'] = 'Idagio'
    metadata['type'] = 'track'

    # --- Logika Genre ---
    genres = []
    try:
        if track_data.get('work').get('genre'):
            genres.append(track_data.get('work').get('genre').get('title'))
        if track_data.get('work').get('subgenre'):
            genres.append(track_data.get('work').get('subgenre').get('title'))
    except AttributeError:
        pass
    if genres:
        metadata['genre'] = ", ".join(genres)
    
    # Sampul
    metadata['cover'] = await _process_cover(metadata, album_data.get("imageUrl"))
    metadata['thumbnail'] = metadata['cover']

    # --- Logika Kualitas ---
    user_id = user.get('user_id')
    preferred_quality_key = idagio_manager.get_user_quality(user_id)
    requested_api_quality = QUALITY_MAP_API[preferred_quality_key] # 90, 70, atau 50
    
    # Cek batas langganan klien (asumsi 'premium' bisa 320k, 'premium+' bisa FLAC)
    # Ini adalah tebakan, API tidak jelas. Kita asumsikan semua akun premium bisa FLAC.
    
    chosen_api_quality = 0
    
    if requested_api_quality == 90:
        chosen_api_quality = 90
    elif requested_api_quality == 70:
        chosen_api_quality = 70
    else:
        chosen_api_quality = 50
        
    # TODO: Perlu cek apakah kualitas yang diminta tersedia di track
    # Untuk saat ini, kita asumsikan 320k (70) selalu ada.
    if chosen_api_quality == 90:
        # Fallback jika FLAC tidak tersedia?
        # Untuk saat ini, kita coba saja minta 90.
        pass
    
    if chosen_api_quality == 0:
        chosen_api_quality = 70 # Default fallback ke 320k

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_api_quality]
    
    metadata['download_quality_tier'] = chosen_api_quality # 90, 70, 50
    metadata['download_track_id'] = download_track_id # ID unik untuk stream
    
    if not metadata['download_track_id']:
        raise IdagioError(f"Tidak dapat menemukan ID stream untuk track {track_id}")
    
    return metadata


async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album."""
    client = user['idagio_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        album_data = await asyncio.to_thread(client.get_album, album_id)
    except Exception as e:
        LOGGER.error(f"Idagio: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    # Coba temukan 'albumartist' (composer album)
    try:
        album_artist_obj = [c for c in album_data.get('participants') if c.get('type') == 'composer'][0]
        album_artist_name = album_artist_obj.get('name')
    except (IndexError, AttributeError):
        album_artist_name = "Various Artists"

    metadata['itemid'] = album_id
    metadata['title'] = album_data.get('title')
    metadata['album'] = album_data.get('title')
    metadata['artist'] = album_artist_name # Gunakan nama composer sebagai artis
    metadata['albumartist'] = album_artist_name
    metadata['date'] = album_data.get('publishDate', '1900')[:4]
    metadata['totaltracks'] = str(len(album_data.get('tracks')))
    metadata['provider'] = 'Idagio'
    metadata['type'] = 'album'
    
    # Sampul
    metadata['cover'] = await _process_cover(metadata, album_data.get("imageUrl"))
    metadata['thumbnail'] = metadata['cover']

    metadata['tracks'] = []
    # N+1 calls, tampaknya tidak bisa dihindari dengan API ini
    for track in album_data.get('tracks'):
        try:
            recording_id = track.get('recording').get('id')
            track_meta = await process_track_metadata(
                recording_id, r_id, user, 
                pre_data=None, # Kita tidak punya data track lengkap
                alb_info_pre=album_data
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"Idagio: Gagal memproses track {recording_id} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
