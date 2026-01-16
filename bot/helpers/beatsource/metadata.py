# [GANTI SELURUH FILE: bot/helpers/beatsource/metadata.py]

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
    """Mem-parse URL Beatsource untuk mendapatkan tipe dan ID."""
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


# --- HELPER: LOAD BALANCING ---

def get_shuffled_clients():
    """
    Mengambil daftar klien dari manager dan mengacak urutannya.
    Ini adalah kunci Load Balancing agar beban tidak bertumpuk di satu akun.
    """
    if not beatsource_manager.clients:
        raise BeatsourceError("Tidak ada akun Beatsource yang tersedia/login.")
    
    # Buat salinan list agar tidak merubah urutan asli di manager
    clients = list(beatsource_manager.clients)
    random.shuffle(clients)
    return clients


# --- PROSES METADATA INTI ---

async def process_track_metadata(item_id: str, r_id: str, user: dict):
    """
    Memproses metadata track dengan strategi Multi-Account (Load Balancing).
    """
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}"

    # 1. Ambil daftar klien yang sudah diacak
    clients = get_shuffled_clients()
    
    track_data = None
    release_data = None
    active_client = None

    # 2. Cari Metadata Dasar (Coba setiap akun sampai berhasil)
    for client in clients:
        try:
            track_data = await client.get_track(item_id)
            # Ambil data album/release juga untuk cover art dan tanggal
            release_data = await client.get_release(track_data['release']['id'])
            active_client = client
            # Jika berhasil, berhenti looping
            break
        except Exception:
            continue
            
    if not track_data or not active_client:
        raise BeatsourceError(f"Gagal mengambil metadata Track {item_id} (Mungkin Region Lock di semua akun).")

    try:
        # 3. Tentukan Kualitas Audio
        user_qual = beatsource_manager.get_user_quality(user['user_id'])
        
        # Cek langganan akun yang sedang aktif (active_client)
        sub_status = beatsource_manager.subscription_cache.get(active_client, "basic")
        has_pro_sub = (sub_status == "pro")
        
        # Downgrade jika minta lossless tapi akun cuma basic
        if not has_pro_sub and user_qual in ["lossless", "high"]:
            user_qual = "medium"
        
        # Susun prioritas kualitas
        quality_priority = ["medium"]
        if has_pro_sub:
             if user_qual == "lossless": 
                 quality_priority = ["lossless", "high", "medium"]
             elif user_qual == "high": 
                 quality_priority = ["high", "medium"]
             else: 
                 quality_priority = ["medium"]

        dl_url = None
        final_quality = None
        
        # 4. Cari Link Download (Retry Logic)
        # Kita coba akun 'active_client' dulu. Jika gagal (misal limit), coba akun lain.
        # Urutkan: active_client ditaruh paling depan, sisanya diacak.
        download_candidates = [active_client] + [c for c in clients if c != active_client]
        
        for client in download_candidates:
            # Perbarui prioritas kualitas berdasarkan status sub akun INI
            current_sub = beatsource_manager.subscription_cache.get(client, "basic")
            current_priority = quality_priority if current_sub == "pro" else ["medium"]

            for qual in current_priority:
                try:
                    dl_data = await client.get_track_download(item_id, qual)
                    dl_url = dl_data.get('location')
                    if dl_url:
                        final_quality = qual
                        break
                except Exception: 
                    pass
            
            if dl_url:
                break # Berhasil dapat link
        
        if not dl_url:
            raise BeatsourceError(f"Gagal mendapatkan URL unduhan track {item_id} di semua akun yang tersedia.")

        # 5. Pengisian Metadata ke Dictionary
        track_artists = track_data.get("artists", [])
        release_artists = release_data.get("artists", [])

        meta['title'] = track_data['name']
        if track_data.get('mix_name'):
            meta['title'] += f" ({track_data['mix_name']})"
        
        meta['artist'] = ", ".join([a['name'] for a in track_artists])
        meta['album'] = release_data['name']
        meta['albumartist'] = ", ".join([a['name'] for a in release_artists])
        
        meta['tracknumber'] = str(track_data.get('track_number') or 1)
        meta['totaltracks'] = str(release_data.get('track_count') or 1)
        meta['volume'] = "1"
        meta['totalvolume'] = "1"
        
        meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
        meta['year'] = meta['date'][:4]
        meta['genre'] = track_data.get('genre', {}).get('name', '')
        
        meta['upc'] = release_data.get('upc')
        meta['isrc'] = track_data.get('isrc')
        meta['explicit'] = track_data.get('explicit', False)
        
        label_name = release_data.get('label', {}).get('name', '')
        meta['copyright'] = f"© {meta['year']} {label_name}"
        meta['duration'] = track_data.get('length_ms', 0) // 1000
        
        meta['quality'] = final_quality.capitalize()
        meta['extension'] = 'flac' if final_quality == 'lossless' else 'm4a'
        
        # Cover Art
        img_uri = release_data.get('image', {}).get('dynamic_uri', '')
        meta['cover'] = await create_cover_file(img_uri.format(w=1400, h=1400), meta)
        meta['thumbnail'] = await create_cover_file(img_uri.format(w=400, h=400), meta, thumbnail=True)
        meta['download_url'] = dl_url

        return meta

    except Exception as e:
        LOGGER.error(f"Beatsource Meta Error {item_id}: {e}")
        raise e


async def process_album_metadata(item_id: str, r_id: str, user: dict):
    """Memproses album dengan load balancing saat mengambil info rilis."""
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'
    meta['volume'] = "1"
    meta['totalvolume'] = "1"

    # Load Balancing: Acak klien untuk request metadata album
    clients = get_shuffled_clients()
    
    release_data = None
    active_client = None
    
    for client in clients:
        try:
            release_data = await client.get_release(item_id)
            active_client = client
            break
        except: 
            continue
        
    if not release_data:
        raise BeatsourceError("Gagal mengambil metadata Album (Region Lock di semua akun?).")

    # Ambil semua track (Handling Pagination)
    tracks_list = []
    page = 1
    while True:
        try:
            tracks_data = await active_client.get_release_tracks(item_id, page=page)
            tracks_list.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'):
                break
            page += 1
            if page > 10: break # Safety break
        except:
            break

    if not tracks_list:
        raise BeatsourceError(f"Album {item_id} tidak memiliki track.")

    meta['title'] = release_data['name']
    meta['artist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
    meta['year'] = meta['date'][:4]
    meta['upc'] = release_data.get('upc')
    meta['totaltracks'] = str(len(tracks_list))
    
    img_uri = release_data.get('image', {}).get('dynamic_uri', '')
    meta['cover'] = await create_cover_file(img_uri.format(w=1400, h=1400), meta)
    meta['thumbnail'] = meta['cover']

    # Proses setiap track
    album_is_explicit = False
    tracks_meta_list = []
    
    for i, track_data in enumerate(tracks_list):
        try:
            # Panggil process_track_metadata untuk setiap lagu
            # Ini akan otomatis melakukan load balancing untuk download link tiap lagunya
            track_meta = await process_track_metadata(track_data['id'], r_id, user)
            
            # Override tracknumber agar sesuai urutan album
            track_meta['tracknumber'] = str(i + 1)
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
    """Memproses playlist/chart dengan load balancing."""
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_PLAYLIST"
    meta['type'] = 'playlist'
    meta['volume'] = "1"
    meta['totalvolume'] = "1"

    clients = get_shuffled_clients()
    
    playlist_data = None
    tracks_endpoint = None
    active_client = None

    # Cari apakah ini Playlist atau Chart di semua akun
    for client in clients:
        try:
            # Coba sebagai Playlist
            try:
                playlist_data = await client.get_playlist(item_id)
                tracks_endpoint = client.get_playlist_tracks
            except:
                # Jika gagal, coba sebagai Chart
                playlist_data = await client.get_chart(item_id)
                tracks_endpoint = client.get_chart_tracks
            
            if playlist_data:
                active_client = client
                break
        except:
            continue

    if not playlist_data:
        raise BeatsourceError("Playlist atau Chart tidak ditemukan di semua akun.")

    # Ambil Tracks (Pagination)
    tracks_list_raw = []
    page = 1
    while True:
        try:
            tracks_data = await tracks_endpoint(item_id, page=page)
            tracks_list_raw.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'): break
            page += 1
            if page > 20: break
        except:
            break
        
    # Filter hasil (Struktur playlist beda dengan chart)
    tracks_list = []
    if tracks_endpoint == active_client.get_playlist_tracks:
        for item in tracks_list_raw:
            if item.get('track'):
                tracks_list.append(item['track'])
    else:
        tracks_list = tracks_list_raw

    meta['title'] = playlist_data['name']
    meta['artist'] = playlist_data.get('user', {}).get('name', 'Beatsource')
    meta['totaltracks'] = str(len(tracks_list))
    
    # Cover Art
    cover_uri = playlist_data.get('image', {}).get('dynamic_uri', '')
    if not cover_uri and playlist_data.get("release_images"):
        # Jika cover playlist kosong, ambil dari salah satu rilis di dalamnya
        cover_uri = playlist_data.get("release_images")[0].get("dynamic_uri", "")

    meta['cover'] = await create_cover_file(cover_uri.format(w=1400, h=1400), meta)
    meta['thumbnail'] = meta['cover']

    playlist_is_explicit = False
    tracks_meta_list = []
    
    for i, track_data in enumerate(tracks_list):
        try:
            track_meta = await process_track_metadata(track_data['id'], r_id, user)
            track_meta['tracknumber'] = str(i + 1)
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
