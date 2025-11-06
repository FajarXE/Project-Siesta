# [FILE BARU: bot/helpers/beatsource/metadata.py]

import re
import traceback

from .api import BeatsourceAPI, BeatsourceError
from .manager import beatsource_manager

from ..metadata import metadata, create_cover_file
from ...settings import bot_set
from ...logger import LOGGER

# --- Parsing URL (dari interface.py) ---
BEATSOURCE_URL_REGEX = re.compile(
    r"https?://(?:www\.)?beatsource\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlist|playlists|chart).*/(?P<id>\d+)[^/]*?(?:$|\?)"
)

def custom_url_parse(url: str):
    match = BEATSOURCE_URL_REGEX.search(url)
    if not match:
        raise ValueError(f"Tidak dapat mem-parse URL Beatsource: {url}")

    media_type_str = match.group("type")
    item_id = match.group("id")
    extra = {}

    # Map tipe URL ke tipe internal bot
    if media_type_str == "track":
        media_type = "track"
    elif media_type_str == "release":
        media_type = "album"
    elif media_type_str == "artist":
        media_type = "artist"
    elif media_type_str in ["playlist", "playlists", "chart"]:
        media_type = "playlist"
        # Catat jika ini adalah chart, mungkin berguna nanti
        if media_type_str == "chart":
            extra["is_chart"] = True
    else:
        raise ValueError(f"Tipe media Beatsource tidak diketahui: {media_type_str}")

    return media_type, item_id, extra


# --- Pemrosesan Metadata Inti ---

async def process_track_metadata(item_id: str, r_id: str, user: dict):
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}"

    client, sub_status = beatsource_manager.get_client_and_sub()
    if not client:
        raise BeatsourceError("Tidak ada klien Beatsource yang login dan tersedia.")

    try:
        track_data = await client.get_track(item_id)
        release_data = await client.get_release(track_data['release']['id'])
        
        # --- Logika Kualitas & Langganan (dari interface.py) ---
        
        user_qual = beatsource_manager.get_user_quality(user['user_id'])
        
        # Tentukan kualitas API yang akan diminta
        api_qual_request = user_qual
        
        # Paksa downgrade jika langganan tidak Pro
        has_pro_sub = (sub_status == "pro")
        if not has_pro_sub and (api_qual_request == "lossless" or api_qual_request == "high"):
            LOGGER.warning(f"Beatsource: Akun tidak Pro. Kualitas {api_qual_request} di-downgrade ke 'medium'.")
            api_qual_request = "medium"
        
        # Coba dapatkan URL unduhan
        quality_priority = {
            "lossless": ["lossless", "high", "medium"],
            "high": ["high", "medium"],
            "medium": ["medium"]
        }.get(api_qual_request, ["medium"])
        
        # Hanya gunakan prioritas yang diizinkan oleh langganan
        if not has_pro_sub:
            quality_priority = ["medium"]

        dl_url = None
        final_quality = None

        for qual in quality_priority:
            try:
                dl_data = await client.get_track_download(item_id, qual)
                dl_url = dl_data.get('location')
                if dl_url:
                    final_quality = qual
                    break
            except Exception as e:
                LOGGER.warning(f"Beatsource: Gagal mendapatkan kualitas '{qual}' untuk {item_id}: {e}")
        
        if not dl_url:
            raise BeatsourceError(f"Tidak dapat mengambil URL unduhan untuk track {item_id} dalam kualitas apa pun.")

        # --- Akhir Logika Kualitas ---

        track_artists = track_data.get("artists", [])
        release_artists = release_data.get("artists", [])

        meta['title'] = track_data['name']
        if track_data.get('mix_name'):
            meta['title'] += f" ({track_data['mix_name']})"
        
        meta['artist'] = ", ".join([a['name'] for a in track_artists])
        meta['album'] = release_data['name']
        meta['albumartist'] = ", ".join([a['name'] for a in release_artists])
        
        meta['tracknumber'] = track_data.get('track_number') or 1
        meta['totaltracks'] = release_data.get('track_count') or 1
        meta['volume'] = 1
        meta['totalvolume'] = 1
        
        meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
        meta['year'] = meta['date'][:4]
        meta['genre'] = track_data.get('genre', {}).get('name', '')
        
        meta['upc'] = release_data.get('upc')
        meta['isrc'] = track_data.get('isrc')
        meta['explicit'] = track_data.get('explicit', False)
        
        meta['copyright'] = f"© {meta['year']} {release_data.get('label', {}).get('name', '')}"
        meta['duration'] = track_data.get('length_ms', 0) // 1000
        
        meta['quality'] = final_quality.capitalize()
        meta['extension'] = 'flac' if final_quality == 'lossless' else 'm4a' # Beatsource/Beatport menggunakan AAC (m4a)
        
        meta['cover'] = await create_cover_file(
            release_data.get('image', {}).get('dynamic_uri', '').format(w=1400, h=1400), meta
        )
        meta['thumbnail'] = await create_cover_file(
            release_data.get('image', {}).get('dynamic_uri', '').format(w=400, h=400), meta, thumbnail=True
        )
        meta['download_url'] = dl_url

        return meta

    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata track Beatsource {item_id}: {e}\n{traceback.format_exc()}")
        raise e


async def process_album_metadata(item_id: str, r_id: str, user: dict):
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'

    client, _ = beatsource_manager.get_client_and_sub()
    if not client:
        raise BeatsourceError("Tidak ada klien Beatsource yang login dan tersedia.")

    try:
        release_data = await client.get_release(item_id)
        
        # Paginasi untuk mendapatkan semua track
        tracks_list = []
        page = 1
        while True:
            tracks_data = await client.get_release_tracks(item_id, page=page)
            tracks_list.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'):
                break
            page += 1
            if page > 10: # Pengaman
                LOGGER.warning(f"Beatsource: Album {item_id} memiliki lebih dari 10 halaman, mungkin error?")
                break

        if not tracks_list:
            raise BeatsourceError(f"Album {item_id} tidak memiliki track.")

        release_artists = release_data.get("artists", [])

        meta['title'] = release_data['name']
        meta['artist'] = ", ".join([a['name'] for a in release_artists])
        
        meta['date'] = release_data.get('publish_date', '1970-01-01')[:10]
        meta['year'] = meta['date'][:4]
        meta['upc'] = release_data.get('upc')
        meta['totaltracks'] = len(tracks_list)
        
        meta['cover'] = await create_cover_file(
            release_data.get('image', {}).get('dynamic_uri', '').format(w=1400, h=1400), meta
        )
        meta['thumbnail'] = meta['cover']

        # Proses semua track dalam album
        tracks_meta_list = []
        for i, track_data in enumerate(tracks_list):
            try:
                track_meta = await process_track_metadata(track_data['id'], r_id, user)
                # Override beberapa metadata dengan info album
                track_meta['tracknumber'] = i + 1
                track_meta['totaltracks'] = meta['totaltracks']
                tracks_meta_list.append(track_meta)
            except Exception as e:
                LOGGER.warning(f"Gagal memproses track {track_data['id']} di album Beatsource {item_id}: {e}")
        
        meta['tracks'] = tracks_meta_list
        meta['totaltracks'] = len(tracks_meta_list)
        
        # Ambil kualitas dari track pertama sebagai representasi
        if tracks_meta_list:
            meta['quality'] = tracks_meta_list[0]['quality']

        return meta

    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata album Beatsource {item_id}: {e}\n{traceback.format_exc()}")
        raise e


async def process_playlist_metadata(item_id: str, r_id: str, user: dict, extra: dict):
    meta = metadata.copy()
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] = f"{meta['tempfolder']}{r_id}/Beatsource/{item_id}_PLAYLIST"
    meta['type'] = 'playlist'

    client, _ = beatsource_manager.get_client_and_sub()
    if not client:
        raise BeatsourceError("Tidak ada klien Beatsource yang login dan tersedia.")

    try:
        # --- Logika Fallback Playlist/Chart (dari interface.py) ---
        playlist_data = None
        tracks_endpoint = None
        
        try:
            # Coba sebagai playlist biasa dulu
            playlist_data = await client.get_playlist(item_id)
            tracks_endpoint = client.get_playlist_tracks
            LOGGER.debug(f"Beatsource: {item_id} ditemukan sebagai Playlist.")
        except BeatsourceError as e:
            if "404" in str(e) or "Item tidak ditemukan" in str(e):
                LOGGER.debug(f"Beatsource: Gagal sebagai playlist (404), mencoba sebagai Chart... {item_id}")
                try:
                    # Fallback ke chart
                    playlist_data = await client.get_chart(item_id)
                    tracks_endpoint = client.get_chart_tracks
                    LOGGER.debug(f"Beatsource: {item_id} ditemukan sebagai Chart.")
                except BeatsourceError as e_chart:
                    raise BeatsourceError(f"Gagal mengambil {item_id} sebagai Playlist maupun Chart: {e_chart}")
            else:
                raise e # Lemparkan error asli jika bukan 404

        if not playlist_data or not tracks_endpoint:
            raise BeatsourceError("Gagal menginisialisasi data playlist/chart.")

        # Paginasi untuk mendapatkan semua track
        tracks_list_raw = []
        page = 1
        while True:
            tracks_data = await tracks_endpoint(item_id, page=page)
            tracks_list_raw.extend(tracks_data.get('results', []))
            if not tracks_data.get('next'):
                break
            page += 1
            if page > 20: # Pengaman
                LOGGER.warning(f"Beatsource: Playlist {item_id} memiliki lebih dari 20 halaman, mungkin error?")
                break
        
        # Response /playlist/tracks membungkus track di { 'track': ... }
        # Response /chart/tracks tidak
        tracks_list = []
        if tracks_endpoint == client.get_playlist_tracks:
            for item in tracks_list_raw:
                if item.get('track'):
                    tracks_list.append(item['track'])
        else:
            tracks_list = tracks_list_raw

        if not tracks_list:
            raise BeatsourceError(f"Playlist {item_id} tidak memiliki track.")

        meta['title'] = playlist_data['name']
        meta['artist'] = playlist_data.get('user', {}).get('name', 'Beatsource')
        meta['totaltracks'] = len(tracks_list)
        
        cover_uri = playlist_data.get('image', {}).get('dynamic_uri', '')
        if not cover_uri: # Fallback untuk playlist (bukan chart)
             release_images = playlist_data.get("release_images")
             if release_images and isinstance(release_images, list) and len(release_images) > 0:
                 cover_uri = release_images[0].get("dynamic_uri", "")

        meta['cover'] = await create_cover_file(
            cover_uri.format(w=1400, h=1400), meta
        )
        meta['thumbnail'] = meta['cover']

        # Proses semua track dalam playlist
        tracks_meta_list = []
        for i, track_data in enumerate(tracks_list):
            try:
                track_meta = await process_track_metadata(track_data['id'], r_id, user)
                track_meta['tracknumber'] = i + 1
                track_meta['totaltracks'] = meta['totaltracks']
                tracks_meta_list.append(track_meta)
            except Exception as e:
                LOGGER.warning(f"Gagal memproses track {track_data['id']} di playlist Beatsource {item_id}: {e}")
        
        meta['tracks'] = tracks_meta_list
        meta['totaltracks'] = len(tracks_meta_list)
        
        if tracks_meta_list:
            meta['quality'] = tracks_meta_list[0]['quality']

        return meta

    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata playlist Beatsource {item_id}: {e}\n{traceback.format_exc()}")
        raise e
