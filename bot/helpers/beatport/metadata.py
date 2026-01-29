# [GANTI SELURUH FILE: bot/helpers/beatport/metadata.py]

import copy
import re
import aiohttp
import urllib.parse
import logging
import os 
import traceback 
import random 
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .api import BeatportAPI, BeatportError
from bot.logger import LOGGER

# --- IMPOR MANAGER ---
from .manager import beatport_manager

# Tentukan path fallback secara eksplisit
FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

# --- Kualitas (Berdasarkan interface.py) ---
QUALITY_MAP = {
    "lossless": "lossless", # FLAC
    "high": "high",       # 256k AAC
    "medium": "medium"    # 128k AAC
}

# --- FUNGSI HELPER ---
def truncate_artist_list(artist_str: str, max_len: int = 200) -> str: 
    """Memotong daftar artis agar tidak terlalu panjang untuk nama file."""
    if len(artist_str) > max_len:
        return artist_str[:max_len] + "..."
    return artist_str

async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] != "0" and metadata['upc'] != "":
            upc_url = f"https://itunes.apple.com/lookup?upc={metadata['upc']}&entity=album&limit=1"
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            return artwork_url.replace('100x100bb.jpg', '1400x1400bb.jpg')
        if metadata.get('albumartist') and metadata.get('album'):
            artist_to_search = metadata.get('artist_raw', metadata.get('albumartist'))
            search_term = urllib.parse.quote(f"{artist_to_search} {metadata['album']}")
            search_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=5"
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        for result in data['results']:
                            itunes_album = result.get('collectionName', '').lower()
                            itunes_artist = result.get('artistName', '').lower()
                            local_album = metadata['album'].lower()
                            local_artist = artist_to_search.lower()
                            if (local_album in itunes_album or itunes_album in local_album) and \
                               (local_artist in itunes_artist):
                                artwork_url = result.get('artworkUrl100')
                                if artwork_url:
                                    return artwork_url.replace('100x100bb.jpg', '1400x1400bb.jpg')
    except Exception as e:
        logging.warning(f"Pencarian sampul iTunes gagal untuk UPC {metadata.get('upc')}: {e}")
    return None


def custom_url_parse(link: str):
    """
    Mengekstrak Tipe dan ID dari URL Beatport.
    """
    match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/.+?/(?P<id>\d+)(?:$|[?#])", link)
    
    if not match:
        # Fallback regex untuk kasus URL tanpa slug
        match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/(?P<id>\d+)(?:$|[?#])", link)
    
    if not match:
        raise BeatportError(f"URL Beatport tidak valid atau format tidak dikenali: {link}")

    media_type_str = match.group("type")
    media_id = match.group("id")

    if media_type_str == "track":
        media_type = "track"
    elif media_type_str == "release":
        media_type = "album"
    elif media_type_str == "artist":
        media_type = "artist"
    elif media_type_str in ["playlists", "chart"]:
        media_type = "playlist"
        
    return media_type, media_id, {"is_chart": media_type_str == "chart"}


async def _generate_artwork_url(dynamic_uri: str, size: int = 1400):
    res_pattern = re.compile(r"\d{3,4}x\d{3,4}")
    match = re.search(res_pattern, dynamic_uri)
    if match:
        dynamic_uri = re.sub(res_pattern, "{w}x{h}", dynamic_uri)
    return dynamic_uri.format(w=size, h=size)


async def _process_cover(metadata: dict, beatport_url: str):
    cover_url = None
    try:
        async with aiohttp.ClientSession() as session:
            logging.debug(f"Mencari sampul di iTunes untuk {metadata['album']}...")
            cover_url = await get_itunes_cover_url(metadata, session)
    except Exception as e:
        logging.warning(f"Sesi pencarian sampul iTunes gagal: {e}")

    if not cover_url and beatport_url:
        logging.debug(f"iTunes gagal, menggunakan sampul Beatport.")
        cover_url = beatport_url

    final_cover_path_or_url = cover_url
    if not cover_url:
        if os.path.exists(FALLBACK_IMAGE_PATH):
            logging.warning(f"Semua sumber online gagal, menggunakan fallback lokal: {FALLBACK_IMAGE_PATH}")
            final_cover_path_or_url = FALLBACK_IMAGE_PATH
        else:
            logging.error(f"SEMUA SUMBER GAGAL, dan fallback lokal TIDAK DITEMUKAN di {FALLBACK_IMAGE_PATH}")
            
    return await create_cover_file(final_cover_path_or_url, metadata)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, fetch_stream: bool = True):
    """
    Memproses metadata untuk satu lagu dengan MULTI-ACCOUNT LOAD BALANCING.
    Args:
        fetch_stream: Jika False, melewati proses download URL (untuk playlist/album agar tidak expired).
    """
    
    primary_client = user.get('beatport_api')
    if not primary_client and beatport_manager.clients:
        primary_client = beatport_manager.clients[0]
        
    available_clients = []
    if primary_client:
        available_clients.append(primary_client)
        
    if beatport_manager and beatport_manager.clients:
        for other_client in beatport_manager.clients:
            if other_client != primary_client:
                available_clients.append(other_client)

    # --- LOAD BALANCING: ACAK CLIENT ---
    random.shuffle(available_clients)
    
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    track_data = pre_data
    if not track_data:
        for client in available_clients:
            try:
                track_data = await client.get_track(track_id)
                break
            except Exception:
                continue
    
    if not track_data:
        raise BeatportError(f"Gagal mendapatkan metadata dasar track {track_id} (cek ID atau Region).")

    try:
        # Cek ketersediaan (kadang API tetap return data meski unavailable)
        if track_data.get("is_available_for_streaming") is False:
             # Kita log warning saja, karena kadang bisa didownload meski flag ini false di beberapa region
             LOGGER.warning(f"Track '{track_data.get('name')}' flag is_available_for_streaming = False.")
             
        if track_data.get("preorder"):
            raise BeatportError(f"Track '{track_data.get('name')}' adalah pre-order!")
    except Exception as e:
        LOGGER.error(f"Beatport: Validasi track {track_id} gagal: {e}")
        raise e

    album_id = track_data.get("release").get("id")
    album_data = {}
    
    # Ambil data album (untuk cover/UPC)
    for client in available_clients:
        try:
            album_data = await client.get_release(album_id)
            break
        except: pass
    
    metadata['itemid'] = track_id
    
    title = track_data.get("name")
    if track_data.get("mix_name"):
        title += f" ({track_data.get('mix_name')})"
    metadata['title'] = title
    
    artist_raw = ", ".join([a.get("name") for a in track_data.get("artists", [])])
    albumartist_raw = ", ".join([a.get("name") for a in album_data.get("artists", [])])

    metadata['artist'] = truncate_artist_list(artist_raw)
    metadata['albumartist'] = truncate_artist_list(albumartist_raw)
    metadata['artist_raw'] = artist_raw 
    
    metadata['album'] = album_data.get("name", "Unknown Album")
    metadata['date'] = track_data.get("publish_date")
    
    raw_track_number = str(track_data.get("number", 1))
    metadata['tracknumber'] = raw_track_number.zfill(2)
    
    metadata['totaltracks'] = str(album_data.get("track_count", 1))
    
    metadata['volume'] = "1"
    metadata['totalvolume'] = "1"
    metadata['explicit'] = track_data.get("explicit", False) 
    
    metadata['isrc'] = track_data.get("isrc")
    metadata['upc'] = album_data.get("upc")
    metadata['duration'] = track_data.get("length_ms", 0) // 1000
    
    release_year = track_data.get("publish_date", "N/A")[:4]
    label_name = track_data.get("release", {}).get("label", {}).get("name", "N/A")
    metadata['copyright'] = f"© {release_year} {label_name}"
    
    genres = [track_data.get("genre", {}).get("name")]
    if track_data.get("sub_genre"):
        genres.append(track_data.get("sub_genre").get("name"))
    metadata['genre'] = ", ".join(filter(None, genres))
    
    metadata['provider'] = 'Beatport'
    metadata['type'] = 'track'
    
    bp_cover_url = ""
    if track_data.get("release", {}).get("image", {}).get("dynamic_uri"):
        bp_cover_url = await _generate_artwork_url(track_data.get("release").get("image").get("dynamic_uri"))
    elif album_data.get("image", {}).get("dynamic_uri"):
        bp_cover_url = await _generate_artwork_url(album_data.get("image").get("dynamic_uri"))
        
    metadata['cover'] = await _process_cover(metadata, bp_cover_url)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover_url, 80), metadata, True)

    # --- QUALITY SELECTION ---
    user_id = user.get('user_id')
    if not user_id:
        preferred_quality = beatport_manager.quality
    else:
        preferred_quality = beatport_manager.get_user_quality(user_id)
    
    quality_order = []
    if preferred_quality == "lossless":
        quality_order = ["lossless", "high", "medium"]
    elif preferred_quality == "high":
        quality_order = ["high", "medium"]
    else: 
        quality_order = ["medium"]
    
    quality_map_display = {
        "lossless": ("FLAC", "flac"),
        "high": ("AAC 256", "m4a"),
        "medium": ("AAC 128", "m4a")
    }
    
    stream_data = None

    # --- DOWNLOAD LINK FETCHING (Just-in-Time Support) ---
    if fetch_stream:
        for idx, current_client in enumerate(available_clients):
            for quality_key in quality_order:
                try:
                    stream_data_json = await current_client.get_track_download(track_id, QUALITY_MAP[quality_key])
                    metadata['quality'], metadata['extension'] = quality_map_display[quality_key]
                    stream_data = stream_data_json 
                    LOGGER.info(f"Beatport: URL didapat! Akun #{idx+1}, Q: {quality_key}, ID: {track_id}")
                    break 
                except Exception:
                    continue 
            if stream_data:
                break

        if not stream_data:
            # Jika semua gagal, berikan error spesifik
            raise BeatportError(f"Gagal mendapatkan URL download track {track_id} di semua akun (Region Lock?).")
            
        metadata['download_url'] = stream_data.get("location")
        if not metadata['download_url']:
            raise BeatportError(f"Respons API valid tapi URL kosong (Track: {track_id}).")
    else:
        # Placeholder untuk playlist agar tidak expired
        if preferred_quality == 'lossless':
            metadata['quality'] = "FLAC"
            metadata['extension'] = "flac"
        else:
            metadata['quality'] = "AAC 256"
            metadata['extension'] = "m4a"
        metadata['download_url'] = None

    return metadata


async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album (release) dengan LOAD BALANCING."""
    
    primary_client = user.get('beatport_api')
    if not primary_client and beatport_manager.clients:
        primary_client = beatport_manager.clients[0]
        
    available_clients = []
    if primary_client: available_clients.append(primary_client)
    if beatport_manager and beatport_manager.clients:
        for c in beatport_manager.clients:
            if c != primary_client: available_clients.append(c)
            
    # --- LOAD BALANCING ---
    random.shuffle(available_clients)

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    album_data = None
    active_client = None
    
    for idx, client in enumerate(available_clients):
        try:
            LOGGER.debug(f"Beatport: Mencoba metadata album {album_id} dengan Akun #{idx+1}...")
            album_data = await client.get_release(album_id)
            active_client = client
            LOGGER.info(f"Beatport: Metadata album {album_id} ditemukan di Akun #{idx+1}")
            break
        except Exception as e:
            continue
            
    if not active_client or not album_data:
        raise BeatportError(f"Gagal mendapatkan metadata album {album_id}. Mungkin tidak tersedia di SEMUA region akun Anda.")
    
    client = active_client

    track_links_or_dicts = album_data.get("tracks", [])
    
    if not track_links_or_dicts:
        LOGGER.warning(f"Beatport: Daftar track kosong di get_release. Mencoba fallback...")
        try:
             tracks_list_from_fallback = []
             page = 1
             per_page = 25 
             while True:
                 tracks_data_page = await client.get_release_tracks(album_id, page=page, per_page=per_page)
                 page_results = tracks_data_page.get("results", [])
                 if not page_results: break 
                 tracks_list_from_fallback.extend(page_results)
                 if not tracks_data_page.get("next"): break
                 page += 1
                 if page > 20: break
             track_links_or_dicts = tracks_list_from_fallback 
             if not track_links_or_dicts: raise BeatportError("Fallback track gagal.")
        except Exception as e:
             raise BeatportError(f"Album {album_id} tidak memiliki track atau API gagal: {e}")
    
    total_tracks = len(track_links_or_dicts)

    metadata['itemid'] = album_id
    metadata['title'] = album_data.get("name")
    metadata['album'] = album_data.get("name")
    
    albumartist_raw = ", ".join([a.get("name") for a in album_data.get("artists", [])])
    metadata['albumartist'] = truncate_artist_list(albumartist_raw)
    metadata['artist'] = metadata['albumartist'] 
    metadata['artist_raw'] = albumartist_raw

    metadata['upc'] = album_data.get("upc")
    metadata['date'] = album_data.get("publish_date")
    metadata['totaltracks'] = str(total_tracks)
    metadata['provider'] = 'Beatport'
    metadata['type'] = 'album'
    metadata['volume'] = "1"
    metadata['totalvolume'] = "1"
    metadata['explicit'] = album_data.get("explicit", False)
    
    bp_cover_url = await _generate_artwork_url(album_data.get("image").get("dynamic_uri"))
    metadata['cover'] = await _process_cover(metadata, bp_cover_url)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover_url, 80), metadata, True)

    metadata['tracks'] = []
    total_duration_ms = 0

    for i, track_item in enumerate(track_links_or_dicts):
        try:
            track_data_full = None
            track_id_str = None
            if isinstance(track_item, str):
                track_id_str = track_item.split('/')[-2]
                if not track_id_str.isdigit(): continue 
                track_data_full = await client.get_track(track_id_str)
            elif isinstance(track_item, dict):
                track_data_full = track_item
                track_id_str = track_data_full.get('id')
            
            if not track_data_full or not track_id_str: continue

            total_duration_ms += track_data_full.get("length_ms", 0)
            
            # PENTING: fetch_stream=False agar URL tidak diambil sekarang (Just-in-Time)
            track_meta = await process_track_metadata(str(track_id_str), r_id, user, track_data_full, fetch_stream=False)
            
            track_meta['totaltracks'] = str(total_tracks)
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
            
        except Exception as e:
           LOGGER.warning(f"Beatport: Gagal memproses track (Item: {track_item}) di album: {e}")
           continue

    metadata['duration'] = total_duration_ms // 1000
    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata


async def process_playlist_metadata(playlist_id: str, r_id: str, user: dict, extra: dict):
    """Memproses metadata untuk playlist/chart dengan LOAD BALANCING."""
    
    primary_client = user.get('beatport_api')
    if not primary_client and beatport_manager.clients:
        primary_client = beatport_manager.clients[0]
        
    available_clients = []
    if primary_client: available_clients.append(primary_client)
    if beatport_manager and beatport_manager.clients:
        for c in beatport_manager.clients:
            if c != primary_client: available_clients.append(c)

    # --- LOAD BALANCING ---
    random.shuffle(available_clients)

    active_client = None
    playlist_data = None
    is_chart = extra.get("is_chart", False)
    
    for idx, client in enumerate(available_clients):
        try:
            if is_chart:
                playlist_data = await client.get_chart(playlist_id)
            else:
                playlist_data = await client.get_playlist(playlist_id)
            active_client = client
            LOGGER.info(f"Beatport: Playlist/Chart ditemukan di Akun #{idx+1}")
            break
        except Exception:
            continue
            
    if not active_client or not playlist_data:
        raise BeatportError(f"Gagal mendapatkan metadata Playlist/Chart {playlist_id} di semua akun.")

    client = active_client

    if is_chart:
        tracks_data = await client.get_chart_tracks(playlist_id, per_page=100)
    else:
        tracks_data = await client.get_playlist_tracks(playlist_id, per_page=100)

    tracks = tracks_data.get("results", [])
    total_tracks = tracks_data.get("count", len(tracks))

    for page in range(2, (total_tracks - 1) // 100 + 2):
        if is_chart:
            tracks_page = await client.get_chart_tracks(playlist_id, page=page, per_page=100)
        else:
            tracks_page = await client.get_playlist_tracks(playlist_id, page=page, per_page=100)
        tracks.extend(tracks_page.get("results", []))
    
    if not tracks:
        raise BeatportError(f"Playlist/Chart {playlist_id} tidak memiliki track.")
        
    if not is_chart:
        tracks = [t.get("track") for t in tracks if t.get("track")]

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = playlist_id
    metadata['title'] = playlist_data.get("name")
    metadata['totaltracks'] = str(total_tracks)
    metadata['duration'] = sum([t.get("length_ms", 0) for t in tracks]) // 1000
    metadata['provider'] = 'Beatport'
    metadata['type'] = 'playlist'
    
    if is_chart:
        artist_raw = playlist_data.get("person", {}).get("owner_name", "Beatport")
        metadata['artist'] = truncate_artist_list(artist_raw)
        metadata['artist_raw'] = artist_raw
        bp_cover_url = await _generate_artwork_url(playlist_data.get("image").get("dynamic_uri"))
    else:
        metadata['artist'] = "User Playlist" 
        bp_cover_url = await _generate_artwork_url(playlist_data.get("release_images")[0])

    metadata['cover'] = await _process_cover(metadata, bp_cover_url)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover_url, 80), metadata, True)

    metadata['tracks'] = []
    for i, track_data in enumerate(tracks):
        try:
            # PENTING: fetch_stream=False agar URL tidak diambil sekarang
            track_meta = await process_track_metadata(str(track_data['id']), r_id, user, track_data, fetch_stream=False)
            
            track_meta['tracknumber'] = str(i + 1).zfill(2)
            
            metadata['tracks'].append(track_meta)
        except Exception as e:
           LOGGER.warning(f"Beatport: Gagal memproses track {track_data.get('id')} di playlist: {e}")
           continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk playlist {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
