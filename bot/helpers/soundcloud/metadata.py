# [GANTI FILE: bot/helpers/soundcloud/metadata.py]

import copy
import re
import aiohttp
import logging
import os 
import urllib.parse 
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
        return artwork_url.replace('-large', '-original').replace('-t500x500', '-original')
    return None

# --- TAMBAHAN BARU: Fungsi Pencarian iTunes ---
# (Fungsi ini disalin dari modul Beatport/Deezer Anda)
async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    """Mencari sampul di iTunes berdasarkan UPC atau Nama Artis/Album."""
    try:
        # 1. Coba berdasarkan UPC (Paling Akurat)
        upc = metadata.get('upc') or metadata.get('isrc') # Coba ISRC jika UPC tidak ada
        if upc and upc != "0" and upc != "":
            # Gunakan 'term' untuk UPC/ISRC karena 'lookup?upc=' terkadang gagal
            search_term = urllib.parse.quote(upc)
            upc_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=1"
            
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            LOGGER.debug(f"iTunes: Sampul ditemukan via UPC/ISRC: {upc}")
                            return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
                            
        # 2. Coba berdasarkan Artis + Album (Fallback)
        artist = metadata.get('albumartist') or metadata.get('artist')
        album = metadata.get('album')
        
        if artist and album:
            search_term = urllib.parse.quote(f"{artist} {album}")
            search_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=5"
            
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        for result in data['results']:
                            itunes_album = result.get('collectionName', '').lower()
                            itunes_artist = result.get('artistName', '').lower()
                            local_album = album.lower()
                            local_artist = artist.lower()
                            
                            # Coba cari kecocokan
                            if (local_album in itunes_album or itunes_album in local_album) and \
                               (local_artist in itunes_artist or itunes_artist in local_artist):
                                artwork_url = result.get('artworkUrl100')
                                if artwork_url:
                                    LOGGER.debug(f"iTunes: Sampul ditemukan via Artis/Album: {artist} - {album}")
                                    return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
                                    
    except Exception as e:
        logging.warning(f"Pencarian sampul iTunes gagal: {e}")
    
    LOGGER.debug("iTunes: Tidak ada sampul yang ditemukan.")
    return None
# --- AKHIR TAMBAHAN BARU ---


# --- FUNGSI YANG HILANG (DIKEMBALIKAN) ---
async def custom_url_parse(link: str, client: SoundcloudAPI):
    """
    Menggunakan endpoint 'resolve' API untuk mendapatkan Tipe dan ID.
    Ini berbeda dari Beatport/Deezer karena URL SC tidak memiliki ID.
    """
    try:
        # 'link' di sini adalah URL panjang (sudah di-resolve dari on.soundcloud.com)
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
# --- AKHIR FUNGSI YANG HILANG ---


async def _process_cover(metadata: dict, art_url_base: str | None):
    """
    Helper untuk mengambil dan memproses sampul.
    Alur: iTunes -> SC Original -> SC Large -> Fallback Lokal
    """
    
    urls_to_try = []
    
    # 1. Prioritas #1: Coba iTunes
    try:
        async with aiohttp.ClientSession() as session:
            itunes_url = await get_itunes_cover_url(metadata, session)
            if itunes_url:
                urls_to_try.append(itunes_url)
    except Exception as e:
        LOGGER.warning(f"Sesi pencarian sampul iTunes gagal: {e}")

    # 2. Prioritas #2 & #3: Tambahkan URL Soundcloud
    if art_url_base:
        urls_to_try.append(artwork_url_format(art_url_base)) # Coba -original
        if artwork_url_format(art_url_base) != art_url_base:
             urls_to_try.append(art_url_base) # Coba -large (fallback)
    
    # 3. Prioritas #4: Tambahkan Fallback Lokal
    fallback_image_path = os.path.join(Config.WORK_DIR, "project-siesta.png")
    # Kita akan gunakan ini sebagai upaya terakhir
    
    # 4. Loop melalui URL yang ditemukan dan coba unduh
    for url in urls_to_try:
        if not url: # Lewati jika URL None (misal iTunes gagal)
            continue
            
        LOGGER.debug(f"Mencoba mengunduh cover art: {url}")
        try:
            cover_path = await create_cover_file(url, metadata)
            # Jika berhasil (tidak ada exception), kembalikan path
            LOGGER.debug(f"Berhasil mengunduh cover art dari: {url}")
            return cover_path
        
        except Exception as e:
            # Log error (misal 404) tapi jangan hentikan loop
            LOGGER.warning(f"Gagal mengunduh cover art dari {url}: {e}")
            continue # Coba URL berikutnya

    # 5. Jika semua URL online gagal, gunakan fallback lokal
    LOGGER.warning("Semua sumber sampul online gagal. Mencoba fallback lokal...")
    try:
        # Coba paksa gunakan fallback
        cover_path = await create_cover_file(fallback_image_path, metadata)
        return cover_path
    except Exception as e:
        # Ini adalah error final (misal: project-siesta.png tidak ada)
        LOGGER.error(f"Gagal menggunakan fallback lokal {fallback_image_path}: {e}")
        return fallback_image_path # Kembalikan path (kosong)


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
    
    # ----- Pastikan tidak ada nilai None -----
    metadata['title'] = track_data.get('title') or 'N/A'
    
    artist_str = track_data.get('user', {}).get('username')
    if publisher_meta.get('artist'):
         artist_str = publisher_meta.get('artist')
         
    metadata['artist'] = ", ".join(artists_split(artist_str)) or ''
    
    metadata['album'] = publisher_meta.get('album_title') or ''
    metadata['albumartist'] = metadata['artist']
    
    metadata['date'] = (track_data.get('created_at') or '').split('T')[0]
    metadata['year'] = get_release_year(track_data)
    
    metadata['tracknumber'] = str(track_data.get('track_number') or 1)
    metadata['totaltracks'] = str(track_data.get('full_duration', 0) // track_data.get('duration', 1) or 1)
    
    metadata['genre'] = track_data.get('genre') or ''
    metadata['isrc'] = publisher_meta.get('isrc') or ''
    metadata['upc'] = publisher_meta.get('upc_or_ean') or '' # (Untuk iTunes)
    metadata['copyright'] = publisher_meta.get('p_line') or ''
    metadata['duration'] = track_data.get('duration', 0) // 1000
    
    metadata['provider'] = 'Soundcloud'
    metadata['type'] = 'track'
    
    # --- PERBAIKAN: Tambahkan Explicit & TotalVolumes ---
    metadata['explicit'] = track_data.get('explicit', False)
    metadata['totalvolumes'] = "1" # SoundCloud tidak punya data disk
    metadata['discnumber'] = "1"
    # --- BATAS PERBAIKAN ---

    # --- Sampul (MODIFIKASI) ---
    art_url_base = track_data.get('artwork_url') or track_data.get('user', {}).get('avatar_url')
    
    # Panggil _process_cover yang baru.
    metadata['cover'] = await _process_cover(metadata, art_url_base)
    
    # Buat thumbnail (ini bisa pakai -large atau -t300x300)
    thumb_url = (art_url_base or '').replace('-original', '-t300x300').replace('-large', '-t300x300')
    metadata['thumbnail'] = await create_cover_file(thumb_url, metadata, True)

    
    # --- Logika Kualitas & Unduhan ---
    
    preferred_quality = soundcloud_manager.get_user_quality(user['user_id'])
    stream_url = None
    download_type = None
    
    if preferred_quality == 'original' and track_data.get('downloadable') and track_data.get('has_downloads_left', True):
        LOGGER.debug(f"Soundcloud: Mencoba 'original download' untuk track {track_id}")
        dl_url = await client.get_track_download(track_id)
        if dl_url:
            stream_url = dl_url
            download_type = 'original'
            metadata['quality'] = 'Original'
            metadata['extension'] = 'dat'

    if not stream_url and track_data.get('streamable'):
        LOGGER.debug(f"Soundcloud: Mencari stream (progressive/hls) untuk track {track_id}")
        
        found_url = None
        found_type = None
        
        for transcoding in track_data.get('media', {}).get('transcodings', []):
            protocol = transcoding.get('format', {}).get('protocol')
            
            if protocol == 'progressive':
                found_url = transcoding.get('url')
                found_type = 'progressive'
                metadata['quality'] = 'MP3 128k' # Asumsi
                metadata['extension'] = 'mp3'
                break 
        
        if not found_url:
            for transcoding in track_data.get('media', {}).get('transcodings', []):
                protocol = transcoding.get('format', {}).get('protocol')
                if protocol == 'hls':
                    found_url = transcoding.get('url')
                    found_type = 'hls'
                    metadata['quality'] = 'AAC 128k' # Asumsi
                    metadata['extension'] = 'm4a'
                    break
                    
        if found_url and found_type:
            try:
                stream_url = await client.get_track_stream_link(
                    found_url, 
                    track_data['track_authorization']
                )
                download_type = found_type
            except Exception as e:
                LOGGER.error(f"Soundcloud: Gagal resolve stream link: {e}")

    if not stream_url or not download_type:
        raise SoundcloudError(f"Track '{metadata['title']}' tidak streamable atau downloadable.")

    metadata['download_url'] = stream_url
    metadata['download_type'] = download_type
    
    return metadata


async def process_playlist_or_album(item_id: str, r_id: str, user: dict, pre_data: dict, media_type: str):
    """Memproses metadata untuk playlist atau album."""
    client: SoundcloudAPI = user['soundcloud_api']
    
    try:
        data = pre_data 
    except Exception as e:
        LOGGER.error(f"Soundcloud: Gagal mendapatkan metadata {media_type} {item_id}: {e}")
        raise e

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = str(item_id)
    metadata['type'] = media_type 
    metadata['provider'] = 'Soundcloud'
    
    # --- PERBAIKAN: Tambahkan Explicit & TotalVolumes ---
    metadata['explicit'] = data.get('explicit', False)
    metadata['totalvolumes'] = "1" # SoundCloud tidak punya data disk
    # --- BATAS PERBAIKAN ---

    metadata['title'] = data.get('title') or 'N/A'
    metadata['artist'] = data.get('user', {}).get('username') or ''
    metadata['albumartist'] = metadata['artist']
    metadata['album'] = metadata['title'] if media_type == 'album' else '' # (Untuk iTunes)
    metadata['date'] = (data.get('created_at') or '').split('T')[0]
    metadata['year'] = get_release_year(data)
    metadata['upc'] = data.get('upc_or_ean') or '' # (Untuk iTunes)
    
    art_url_base = data.get('artwork_url') or data.get('user', {}).get('avatar_url')
    
    # Panggil _process_cover yang baru
    metadata['cover'] = await _process_cover(metadata, art_url_base)
    
    thumb_url = (art_url_base or '').replace('-original', '-t300x300').replace('-large', '-t300x300')
    metadata['thumbnail'] = await create_cover_file(thumb_url, metadata, True)

    # --- Ambil Tracks ---
    tracks_list = data.get('tracks', [])
    if not tracks_list:
        raise SoundcloudError(f"{media_type.capitalize()} '{metadata['title']}' tidak memiliki lagu.")
    
    LOGGER.debug(f"Soundcloud: Mengambil data track lengkap untuk {media_type} {item_id}...")
    try:
        tracks_dict = await client.get_tracks_from_tracklist(tracks_list)
    except Exception as e:
        raise SoundcloudError(f"Gagal mengambil daftar track lengkap: {e}")

    metadata['tracks'] = []
    track_count = 0
    
    for i, track_stub in enumerate(tracks_list):
        track_id = track_stub.get('id')
        if not track_id or track_id not in tracks_dict:
            LOGGER.warning(f"Soundcloud: Melewatkan track {track_id} (tidak ditemukan) di {media_type}.")
            continue
            
        track_data = tracks_dict[track_id]
        
        try:
            track_data["track_number"] = i + 1 
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
