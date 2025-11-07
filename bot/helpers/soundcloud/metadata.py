# [FILE BARU: bot/helpers/soundcloud/metadata.py]

import copy
import re
import aiohttp
import logging
import os 
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .api import SoundcloudAPI, SoundcloudError
from .manager import soundcloud_manager
from bot.logger import LOGGER

# --- Helper dari interface.py (diadaptasi) ---

def artists_split(artists_string: str) -> list:
    """Mengurai string artis dari Soundcloud."""
    if not artists_string:
        return []
    # Logika dari file Anda
    return artists_string.replace(' & ', ', ').replace(' and ', ', ').replace(' x ', ', ').split(', ')

def get_release_year(data: dict) -> int | None:
    """Mendapatkan tahun rilis dari berbagai field tanggal."""
    release_date = ''
    if data.get('release_date'):
        release_date = data['release_date']
    elif data.get('display_date'):
        release_date = data['display_date']
    elif data.get('created_at'):
        release_date = data['created_at']
    
    if release_date:
        try:
            return int(release_date.split('-')[0])
        except:
            pass
    return None

def artwork_url_format(artwork_url: str | None) -> str | None:
    """Mengganti URL sampul 'large' menjadi 'original'."""
    if artwork_url:
        # Logika dari file Anda: -large -> -original
        # Juga menangani -t500x500 -> -original
        return artwork_url.replace('-large', '-original').replace('-t500x500', '-original')
    return None

# --- Fungsi Parser Utama ---

async def custom_url_parse(link: str, client: SoundcloudAPI):
    """
    Menggunakan endpoint 'resolve' API untuk mendapatkan Tipe dan ID.
    Ini berbeda dari Beatport/Deezer karena URL SC tidak memiliki ID.
    """
    try:
        data = await client.resolve_url(link)
    except Exception as e:
        LOGGER.error(f"Soundcloud: Gagal me-resolve URL {link}: {e}")
        raise SoundcloudError(f"URL tidak valid atau tidak dapat ditemukan: {e}")

    kind = data.get('kind')
    media_id = str(data.get('id'))
    media_type = None

    if kind == 'track':
        media_type = 'track'
    elif kind == 'user':
        media_type = 'artist'
    elif kind == 'playlist':
        # Logika dari interface.py: bedakan album dan playlist
        if data.get('is_album', False):
            media_type = 'album'
        else:
            media_type = 'playlist'
    
    if not media_type or not media_id:
        raise SoundcloudError(f"Tipe media '{kind}' tidak didukung.")

    # Optimalisasi: Kirim data yang sudah di-resolve 
    # agar tidak perlu di-fetch lagi.
    return media_type, media_id, {"pre_data": data}


async def _process_cover(metadata: dict, artwork_url: str | None):
    """Helper untuk mengambil dan memproses sampul."""
    final_cover_path_or_url = artwork_url
    
    # Soundcloud tidak punya UPC, jadi tidak perlu cari iTunes.
    # Kita juga bisa tambahkan fallback lokal jika artwork_url None.
    
    if not final_cover_path_or_url:
        # (Opsional) Anda bisa tambahkan fallback ke avatar artis jika sampul track null
        LOGGER.warning(f"Soundcloud: Tidak ada sampul ditemukan untuk {metadata.get('title')}.")
        # (Opsional) Gunakan fallback global jika ada
        # FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png") ...
        pass 
        
    return await create_cover_file(final_cover_path_or_url, metadata)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None):
    """Memproses metadata untuk satu lagu."""
    client: SoundcloudAPI = user['soundcloud_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        track_data = pre_data if pre_data else await client.get_track(track_id)
    except Exception as e:
        LOGGER.error(f"Soundcloud: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = str(track_id)
    
    # --- Info Dasar (dari get_track_info) ---
    publisher_meta = track_data.get('publisher_metadata', {}) or {}
    
    metadata['title'] = track_data.get('title', 'N/A')
    # Artis utama adalah pemilik track
    metadata['artist'] = ", ".join(artists_split(track_data.get('user', {}).get('username')))
    # Jika ada artis di metadata, gunakan itu (seringkali lebih bersih)
    if publisher_meta.get('artist'):
         metadata['artist'] = ", ".join(artists_split(publisher_meta.get('artist')))
         
    metadata['album'] = publisher_meta.get('album_title')
    metadata['albumartist'] = metadata['artist'] # Asumsi sederhana
    
    metadata['date'] = track_data.get('created_at', '').split('T')[0]
    metadata['year'] = get_release_year(track_data)
    
    metadata['tracknumber'] = str(track_data.get('track_number', 1))
    metadata['totaltracks'] = str(track_data.get('full_duration', 0) // track_data.get('duration', 1)) # Tebakan
    
    metadata['genre'] = track_data.get('genre')
    metadata['isrc'] = publisher_meta.get('isrc')
    metadata['copyright'] = publisher_meta.get('p_line')
    metadata['duration'] = track_data.get('duration', 0) // 1000
    
    metadata['provider'] = 'Soundcloud'
    metadata['type'] = 'track'
    
    # --- Sampul ---
    art_url = artwork_url_format(track_data.get('artwork_url') or track_data.get('user', {}).get('avatar_url'))
    metadata['cover'] = await _process_cover(metadata, art_url)
    metadata['thumbnail'] = await create_cover_file(art_url.replace('-original', '-large'), metadata, True) # thumbnail
    
    # --- Logika Kualitas & Unduhan (Paling Penting) ---
    
    preferred_quality = soundcloud_manager.get_user_quality(user['user_id'])
    stream_url = None
    download_type = None # 'original', 'progressive', atau 'hls'
    
    # 1. Coba 'Original' jika diminta dan tersedia
    if preferred_quality == 'original' and track_data.get('downloadable') and track_data.get('has_downloads_left', True):
        LOGGER.debug(f"Soundcloud: Mencoba 'original download' untuk track {track_id}")
        dl_url = await client.get_track_download(track_id)
        if dl_url:
            stream_url = dl_url
            download_type = 'original'
            metadata['quality'] = 'Original'
            # Ekstensi akan ditentukan oleh handler berdasarkan Content-Type nanti
            metadata['extension'] = 'dat' # Placeholder

    # 2. Jika 'Original' gagal atau tidak diminta, cari 'Stream'
    if not stream_url and track_data.get('streamable'):
        LOGGER.debug(f"Soundcloud: Mencari stream (progressive/hls) untuk track {track_id}")
        
        # Logika dari interface.py: cari progressive dulu, baru hls
        found_url = None
        found_type = None
        
        for transcoding in track_data.get('media', {}).get('transcodings', []):
            protocol = transcoding.get('format', {}).get('protocol')
            
            if protocol == 'progressive':
                # Ini adalah URL MP3/OGG langsung
                found_url = transcoding.get('url')
                found_type = 'progressive'
                metadata['quality'] = 'MP3 128k' # Asumsi
                metadata['extension'] = 'mp3'
                break # Prioritaskan progressive
        
        # Jika tidak ada progressive, cari HLS
        if not found_url:
            for transcoding in track_data.get('media', {}).get('transcodings', []):
                protocol = transcoding.get('format', {}).get('protocol')
                if protocol == 'hls':
                    # Ini adalah URL M3U8 (AAC)
                    found_url = transcoding.get('url')
                    found_type = 'hls'
                    metadata['quality'] = 'AAC 128k' # Asumsi
                    metadata['extension'] = 'm4a'
                    break
                    
        if found_url and found_type:
            # Kita perlu 'resolve' URL stream ini (dari interface.py)
            try:
                stream_url = await client.get_track_stream_link(
                    found_url, 
                    track_data['track_authorization']
                )
                download_type = found_type
            except Exception as e:
                LOGGER.error(f"Soundcloud: Gagal resolve stream link: {e}")

    # 3. Cek Final
    if not stream_url or not download_type:
        raise SoundcloudError(f"Track '{metadata['title']}' tidak streamable atau downloadable.")

    metadata['download_url'] = stream_url
    metadata['download_type'] = download_type # Penting untuk handler!
    
    return metadata


async def process_playlist_or_album(item_id: str, r_id: str, user: dict, pre_data: dict, media_type: str):
    """Memproses metadata untuk playlist atau album."""
    client: SoundcloudAPI = user['soundcloud_api']
    
    try:
        data = pre_data if pre_data else await client.get_playlist(item_id) # get_playlist/album
    except Exception as e:
        LOGGER.error(f"Soundcloud: Gagal mendapatkan metadata {media_type} {item_id}: {e}")
        raise e

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = str(item_id)
    metadata['type'] = media_type # 'album' atau 'playlist'
    metadata['provider'] = 'Soundcloud'

    metadata['title'] = data.get('title', 'N/A')
    metadata['artist'] = data.get('user', {}).get('username')
    metadata['albumartist'] = metadata['artist']
    metadata['date'] = data.get('created_at', '').split('T')[0]
    metadata['year'] = get_release_year(data)
    
    art_url = artwork_url_format(data.get('artwork_url') or data.get('user', {}).get('avatar_url'))
    metadata['cover'] = await _process_cover(metadata, art_url)
    metadata['thumbnail'] = await create_cover_file(art_url.replace('-original', '-original'), metadata, True)

    # --- Ambil Tracks ---
    tracks_list = data.get('tracks', [])
    if not tracks_list:
        raise SoundcloudError(f"{media_type.capitalize()} '{metadata['title']}' tidak memiliki lagu.")
    
    # Gunakan fungsi dari API untuk melengkapi data track yang hilang
    LOGGER.debug(f"Soundcloud: Mengambil data track lengkap untuk {media_type} {item_id}...")
    try:
        tracks_dict = await client.get_tracks_from_tracklist(tracks_list)
    except Exception as e:
        raise SoundcloudError(f"Gagal mengambil daftar track lengkap: {e}")

    metadata['tracks'] = []
    track_count = 0
    
    # Urutkan berdasarkan urutan asli (tracks_list)
    for i, track_stub in enumerate(tracks_list):
        track_id = track_stub.get('id')
        if not track_id or track_id not in tracks_dict:
            LOGGER.warning(f"Soundcloud: Melewatkan track {track_id} (tidak ditemukan) di {media_type}.")
            continue
            
        track_data = tracks_dict[track_id]
        
        try:
            track_data["track_number"] = i + 1 # Inject track number
            track_meta = await process_track_metadata(str(track_id), r_id, user, pre_data=track_data)
            
            # Gunakan sampul album/playlist
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            
            metadata['tracks'].append(track_meta)
            track_count += 1
        except Exception as e:
            LOGGER.warning(f"Soundcloud: Gagal memproses track {track_id} di {media_type}: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk {media_type} {metadata['title']}")
    
    metadata['totaltracks'] = str(track_count)
    metadata['duration'] = sum(t['duration'] for t in metadata['tracks'])
    metadata['quality'] = metadata['tracks'][0]['quality']
    
    return metadata
