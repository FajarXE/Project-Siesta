# [FILE: bot/helpers/beatsource/metadata.py]

import re
import traceback
import random 
import asyncio

from .api import BeatsourceAPI, BeatsourceError
from .manager import beatsource_manager

from ..metadata import metadata, create_cover_file
from ...settings import bot_set
from ...logger import LOGGER

# --- REGEX URL ---
BEATSOURCE_URL_REGEX = re.compile(
    r"https?://(?:www\.)?beatsource\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlist|playlists|chart).*/(?P<id>\d+)[^/]*?(?:$|\?)"
)

def custom_url_parse(url: str):
    """
    Mem-parse URL Beatsource untuk mendapatkan tipe media dan ID.
    """
    match = BEATSOURCE_URL_REGEX.search(url)
    if not match:
        raise ValueError(f"Tidak dapat mem-parse URL Beatsource: {url}")

    media_type_str = match.group("type")
    item_id = match.group("id")
    extra = {}

    if media_type_str == "track":
        media_type = "track"
    elif media_type_str == "release":
        media_type = "album"
    elif media_type_str == "artist":
        media_type = "artist"
    elif media_type_str in ["playlist", "playlists", "chart"]:
        media_type = "playlist"
        if media_type_str == "chart":
            extra["is_chart"] = True
    else:
        raise ValueError(f"Tipe media Beatsource tidak diketahui: {media_type_str}")

    return media_type, item_id, extra


# --- PROSES METADATA INTI ---

async def process_track_metadata(item_id: str, r_id: str, user: dict, fetch_stream: bool = True):
    """
    Memproses metadata track.
    
    [MODIFIKASI]: Menggunakan client spesifik user (via get_client) untuk:
    1. Mengambil metadata (Judul, Artis) -> Agar tembus Region Lock.
    2. Mengambil URL stream (jika fetch_stream=True) -> Agar kualitas sesuai akun user.
    """
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}"

    # [PENTING] Ambil client aktif untuk user ini
    user_id = user.get('user_id')
    active_client = beatsource_manager.get_client(user_id)
    
    if not active_client:
        raise BeatsourceError("Tidak ada akun Beatsource yang tersedia/login.")

    track_data = None
    release_data = None

    # RETRY LOGIC (Sederhana untuk mengatasi timeout sesaat)
    for attempt in range(2): 
        try:
            track_data = await active_client.get_track(item_id)
            release_data = await active_client.get_release(track_data['release']['id'])
            break
        except Exception as e:
            if attempt == 1: # Log error hanya pada percobaan terakhir
                LOGGER.warning(f"Gagal ambil metadata track {item_id}: {e}")
            await asyncio.sleep(0.5) 
            continue
            
    if not track_data:
        raise BeatsourceError(f"Gagal mengambil metadata Track {item_id} (Mungkin Region Lock/Connection Timeout).")

    try:
        # --- LOGIKA STREAM (JUST-IN-TIME) ---
        dl_url = None
        final_quality = "High" # Default display
        
        # Ambil preferensi kualitas user
        user_qual_pref = beatsource_manager.get_user_quality(user_id)
        meta['quality'] = user_qual_pref.capitalize() 

        if fetch_stream:
            # Tentukan prioritas kualitas berdasarkan setting user
            quality_priority = []
            if user_qual_pref == "lossless":
                quality_priority = ["lossless", "high", "medium"]
            elif user_qual_pref == "high":
                quality_priority = ["high", "medium"]
            else:
                quality_priority = ["medium"]

            # Coba ambil link download sesuai prioritas kualitas
            # Menggunakan active_client milik user
            for qual in quality_priority:
                try:
                    dl_data = await active_client.get_track_download(item_id, qual)
                    dl_url = dl_data.get('location')
                    if dl_url:
                        final_quality = qual
                        break 
                except Exception: pass
            
            if not dl_url:
                raise BeatsourceError(f"Gagal mendapatkan URL unduhan track {item_id}.")
            
            # Set kualitas dan ekstensi final yang didapatkan
            meta['quality'] = final_quality.capitalize()
            meta['extension'] = 'flac' if final_quality == 'lossless' else 'm4a'
        else:
            # Jika fetch_stream=False (misal dari Playlist), set placeholder
            # URL sebenarnya akan diambil nanti di handler.py
            meta['extension'] = 'm4a' 
            if user_qual_pref == 'lossless':
                meta['extension'] = 'flac'

        # --- PENGISIAN FIELD METADATA ---
        track_artists = track_data.get("artists", [])
        release_artists = release_data.get("artists", [])

        meta['title'] = track_data['name']
        if track_data.get('mix_name'):
            meta['title'] += f" ({track_data['mix_name']})"
        
        meta['artist'] = ", ".join([a['name'] for a in track_artists])
        meta['album'] = release_data['name']
        meta['albumartist'] = ", ".join([a['name'] for a in release_artists])
        
        raw_track_number = str(track_data.get('track_number') or 1)
        meta['tracknumber'] = raw_track_number.zfill(2)
        
        meta['totaltracks'] = str(release_data.get('track_count') or 1)
        
        meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
        meta['year'] = meta['date'][:4]
        meta['genre'] = track_data.get('genre', {}).get('name', '')
        
        meta['upc'] = release_data.get('upc')
        meta['isrc'] = track_data.get('isrc')
        meta['explicit'] = track_data.get('explicit', False)
        
        label_name = release_data.get('label', {}).get('name', '')
        meta['copyright'] = f"© {meta['year']} {label_name}"
        meta['duration'] = track_data.get('length_ms', 0) // 1000
        
        # Ambil Cover Art
        img_uri = release_data.get('image', {}).get('dynamic_uri', '')
        if not img_uri and track_data.get('image'):
             img_uri = track_data.get('image', {}).get('dynamic_uri', '')

        if img_uri:
            meta['cover'] = await create_cover_file(img_uri.format(w=1400, h=1400), meta)
            meta['thumbnail'] = await create_cover_file(img_uri.format(w=400, h=400), meta, thumbnail=True)
        
        meta['download_url'] = dl_url # Bisa None jika fetch_stream=False

        return meta

    except Exception as e:
        LOGGER.error(f"Beatsource Meta Error {item_id}: {e}")
        raise e


async def process_album_metadata(item_id: str, r_id: str, user: dict):
    """
    Memproses metadata album.
    """
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'
    meta['volume'] = "1"
    meta['totalvolume'] = "1"

    # [MODIFIKASI] Ambil Client User
    active_client = beatsource_manager.get_client(user.get('user_id'))
    if not active_client:
        raise BeatsourceError("Tidak ada klien Beatsource aktif.")

    try:
        release_data = await active_client.get_release(item_id)
    except Exception as e:
        raise BeatsourceError(f"Gagal mengambil metadata Album: {e}")

    # Ambil semua track (dengan pagination)
    tracks_list = []
    page = 1
    while True:
        try:
            tracks_data = await active_client.get_release_tracks(item_id, page=page)
            tracks_list.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'): break
            page += 1
            if page > 10: break # Safety break
        except: break

    if not tracks_list:
        raise BeatsourceError(f"Album {item_id} tidak memiliki track.")

    # Isi metadata album umum
    meta['title'] = release_data['name']
    meta['artist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
    meta['year'] = meta['date'][:4]
    meta['upc'] = release_data.get('upc')
    meta['totaltracks'] = str(len(tracks_list))
    
    img_uri = release_data.get('image', {}).get('dynamic_uri', '')
    meta['cover'] = await create_cover_file(img_uri.format(w=1400, h=1400), meta)
    meta['thumbnail'] = meta['cover']

    album_is_explicit = False
    tracks_meta_list = []
    
    # Loop setiap track
    for i, track_data in enumerate(tracks_list):
        try:
            # PASS fetch_stream=False agar URL tidak diambil sekarang (biar tidak expired saat antri download)
            track_meta = await process_track_metadata(track_data['id'], r_id, user, fetch_stream=False)
            
            track_meta['tracknumber'] = str(i + 1).zfill(2)
            track_meta['totaltracks'] = meta['totaltracks']
            tracks_meta_list.append(track_meta)
            
            if track_meta['explicit']:
                album_is_explicit = True
        except Exception as e:
            LOGGER.warning(f"Skip track {track_data['id']} di album: {e}")
    
    meta['tracks'] = tracks_meta_list
    meta['explicit'] = album_is_explicit
    
    if tracks_meta_list:
        meta['quality'] = tracks_meta_list[0]['quality']

    return meta


async def process_playlist_metadata(item_id: str, r_id: str, user: dict, extra: dict):
    """
    Memproses metadata playlist atau chart.
    """
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_PLAYLIST"
    meta['type'] = 'playlist'
    meta['volume'] = "1"
    meta['totalvolume'] = "1"

    # [MODIFIKASI] Ambil Client User
    active_client = beatsource_manager.get_client(user.get('user_id'))
    if not active_client:
        raise BeatsourceError("Tidak ada klien Beatsource aktif.")

    playlist_data = None
    tracks_endpoint = None

    # Cek apakah ini Playlist atau Chart
    try:
        try:
            playlist_data = await active_client.get_playlist(item_id)
            tracks_endpoint = active_client.get_playlist_tracks
        except:
            playlist_data = await active_client.get_chart(item_id)
            tracks_endpoint = active_client.get_chart_tracks
    except Exception as e:
        raise BeatsourceError(f"Playlist/Chart tidak ditemukan: {e}")

    # Ambil tracks (pagination)
    tracks_list_raw = []
    page = 1
    while True:
        try:
            tracks_data = await tracks_endpoint(item_id, page=page)
            tracks_list_raw.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'): break
            page += 1
            if page > 20: break # Safety limit 2000 tracks
        except: break
        
    tracks_list = []
    # Normalisasi struktur data (Playlist membungkus track dalam objek 'track')
    if tracks_endpoint == active_client.get_playlist_tracks:
        for item in tracks_list_raw:
            if item.get('track'):
                tracks_list.append(item['track'])
    else:
        tracks_list = tracks_list_raw

    meta['title'] = playlist_data['name']
    meta['artist'] = playlist_data.get('user', {}).get('name', 'Beatsource')
    meta['totaltracks'] = str(len(tracks_list))
    
    cover_uri = playlist_data.get('image', {}).get('dynamic_uri', '')
    if not cover_uri and playlist_data.get("release_images"):
        cover_uri = playlist_data.get("release_images")[0].get("dynamic_uri", "")

    meta['cover'] = await create_cover_file(cover_uri.format(w=1400, h=1400), meta)
    meta['thumbnail'] = meta['cover']

    playlist_is_explicit = False
    tracks_meta_list = []
    
    for i, track_data in enumerate(tracks_list):
        try:
            # PASS fetch_stream=False -> URL diambil nanti di handler
            track_meta = await process_track_metadata(track_data['id'], r_id, user, fetch_stream=False)
            
            track_meta['tracknumber'] = str(i + 1).zfill(2)
            track_meta['totaltracks'] = meta['totaltracks']
            tracks_meta_list.append(track_meta)
            
            if track_meta['explicit']:
                playlist_is_explicit = True
        except Exception as e:
            LOGGER.warning(f"Skip track {track_data['id']} di playlist: {e}")

    meta['tracks'] = tracks_meta_list
    meta['explicit'] = playlist_is_explicit
    
    if tracks_meta_list:
        meta['quality'] = tracks_meta_list[0]['quality']

    return meta
