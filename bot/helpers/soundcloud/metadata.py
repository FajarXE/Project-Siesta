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

# --- Fungsi Pencarian iTunes ---
async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    """Mencari sampul di iTunes berdasarkan UPC atau Nama Artis/Album."""
    try:
        upc = metadata.get('upc') or metadata.get('isrc') 
        if upc and upc != "0" and upc != "":
            search_term = urllib.parse.quote(upc)
            upc_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=1"
            
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
                            
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
                            
                            if (local_album in itunes_album or itunes_album in local_album) and \
                               (local_artist in itunes_artist or itunes_artist in local_artist):
                                artwork_url = result.get('artworkUrl100')
                                if artwork_url:
                                    return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
                                    
    except Exception:
        pass
    return None

async def custom_url_parse(link: str, client: SoundcloudAPI):
    """Menggunakan endpoint 'resolve' API untuk mendapatkan Tipe dan ID."""
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
        if data.get('is_album', False):
            media_type = 'album'
        else:
            media_type = 'playlist'
    
    if not media_type or not media_id:
        raise SoundcloudError(f"Tipe media '{kind}' tidak didukung.")

    return media_type, media_id, {"pre_data": data}


async def _process_cover(metadata: dict, art_url_base: str | None):
    """Helper untuk mengambil dan memproses sampul."""
    urls_to_try = []
    
    try:
        async with aiohttp.ClientSession() as session:
            itunes_url = await get_itunes_cover_url(metadata, session)
            if itunes_url:
                urls_to_try.append(itunes_url)
    except Exception:
        pass

    if art_url_base:
        urls_to_try.append(artwork_url_format(art_url_base)) 
        if artwork_url_format(art_url_base) != art_url_base:
             urls_to_try.append(art_url_base)
    
    fallback_image_path = os.path.join(Config.WORK_DIR, "project-siesta.png")
    
    for url in urls_to_try:
        if not url: continue
        try:
            cover_path = await create_cover_file(url, metadata)
            return cover_path
        except Exception:
            continue

    try:
        cover_path = await create_cover_file(fallback_image_path, metadata)
        return cover_path
    except Exception:
        return fallback_image_path


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None):
    """Memproses metadata untuk satu lagu dengan info tag yang lebih lengkap."""
    client: SoundcloudAPI = user['soundcloud_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        track_data = pre_data if pre_data else await client.get_track(track_id)
    except Exception as e:
        LOGGER.error(f"Soundcloud: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = str(track_id)
    
    # --- PENGAMBILAN DATA TAG UTAMA (Publisher Metadata) ---
    publisher_meta = track_data.get('publisher_metadata', {}) or {}
    
    # 1. Judul
    metadata['title'] = track_data.get('title') or 'N/A'
    
    # 2. Artis
    artist_str = track_data.get('user', {}).get('username')
    if publisher_meta.get('artist'):
         artist_str = publisher_meta.get('artist')
    metadata['artist'] = ", ".join(artists_split(artist_str)) or ''
    
    # 3. Album (Jika kosong, gunakan judul untuk Single)
    album_title = publisher_meta.get('album_title')
    if not album_title:
        # Fallback: jika ini single, biasanya album = judul lagu
        album_title = metadata['title']
    metadata['album'] = album_title
    metadata['albumartist'] = metadata['artist']
    
    # 4. Tanggal & Tahun
    metadata['date'] = (track_data.get('created_at') or '').split('T')[0]
    metadata['year'] = get_release_year(track_data)
    
    # 5. Track Number & Total Tracks
    metadata['tracknumber'] = str(track_data.get('track_number') or 1)
    # Coba hitung total track dari durasi (logika kasar) atau default 1
    metadata['totaltracks'] = str(track_data.get('full_duration', 0) // track_data.get('duration', 1) or 1)
    
    # 6. Disc Number / Part (Soundcloud tidak punya konsep disc, jadi default 1/1)
    metadata['discnumber'] = "1"
    metadata['totaldiscs'] = "1"
    
    # 7. Genre
    metadata['genre'] = track_data.get('genre') or ''
    
    # --- TAG TAMBAHAN (YANG ANDA MINTA) ---
    
    # Composer (Komposer)
    metadata['composer'] = publisher_meta.get('writer_composer') or publisher_meta.get('composer') or ''
    
    # Producer (Produser) - Jarang ada di API SC, kita coba ambil dari description jika perlu, 
    # tapi lebih aman dikosongkan atau disamakan dengan artist jika tidak ada.
    metadata['producer'] = publisher_meta.get('producer') or '' 
    
    # Label / Publisher
    metadata['label'] = publisher_meta.get('publisher') or ''
    metadata['publisher'] = metadata['label'] # Redundansi untuk kompatibilitas
    
    # Copyright
    # Prioritas: c_line -> p_line -> default string
    c_line = publisher_meta.get('c_line')
    p_line = publisher_meta.get('p_line')
    
    if c_line:
        metadata['copyright'] = c_line
    elif p_line:
        metadata['copyright'] = p_line
    else:
        # Fallback copyright ke tahun dan artis
        yr = metadata['year'] or '2026'
        metadata['copyright'] = f"© {yr} {metadata['artist']}"

    # ISRC
    metadata['isrc'] = publisher_meta.get('isrc') or ''
    
    # UPC / BARCODE / EAN
    # Soundcloud biasanya menyimpannya di 'upc_or_ean'
    upc_code = publisher_meta.get('upc_or_ean') or ''
    metadata['upc'] = upc_code
    metadata['barcode'] = upc_code
    metadata['ean'] = upc_code

    # --- Info Teknis Lainnya ---
    metadata['duration'] = track_data.get('duration', 0) // 1000
    metadata['provider'] = 'Soundcloud'
    metadata['type'] = 'track'
    
    metadata['explicit'] = track_data.get('explicit', False)
    # Total Volumes (sama dengan Total Discs)
    metadata['totalvolumes'] = "1" 

    # --- Sampul ---
    art_url_base = track_data.get('artwork_url') or track_data.get('user', {}).get('avatar_url')
    metadata['cover'] = await _process_cover(metadata, art_url_base)
    
    thumb_url = (art_url_base or '').replace('-original', '-t300x300').replace('-large', '-t300x300')
    metadata['thumbnail'] = await create_cover_file(thumb_url, metadata, True)

    # --- Logika Kualitas & Unduhan ---
    
    preferred_quality = soundcloud_manager.get_user_quality(user['user_id'])
    stream_url = None
    download_type = None
    
    # 1. Cek Download Asli
    if preferred_quality == 'original' and track_data.get('downloadable') and track_data.get('has_downloads_left', True):
        LOGGER.debug(f"Soundcloud: Mencoba 'original download' untuk track {track_id}")
        dl_url = await client.get_track_download(track_id)
        if dl_url:
            stream_url = dl_url
            download_type = 'original'
            metadata['quality'] = 'Original'
            metadata['extension'] = 'dat'

    # 2. Cek Stream (Progressive / HLS)
    if not stream_url and track_data.get('streamable'):
        LOGGER.debug(f"Soundcloud: Mencari stream (progressive/hls) untuk track {track_id}")
        
        found_url = None
        found_type = None
        
        transcodings = track_data.get('media', {}).get('transcodings', [])
        
        for transcoding in transcodings:
            format_data = transcoding.get('format', {})
            protocol = format_data.get('protocol')
            mime_type = format_data.get('mime_type', '')
            
            if protocol == 'progressive':
                found_url = transcoding.get('url')
                found_type = 'progressive'
                
                if 'audio/mp4' in mime_type or 'audio/aac' in mime_type:
                    metadata['quality'] = 'AAC 256k' 
                    metadata['extension'] = 'm4a'
                else:
                    metadata['quality'] = 'MP3 128k'
                    metadata['extension'] = 'mp3'
                break 
        
        if not found_url:
            for transcoding in transcodings:
                format_data = transcoding.get('format', {})
                protocol = format_data.get('protocol')
                mime_type = format_data.get('mime_type', '')
                
                if protocol == 'hls':
                    found_url = transcoding.get('url')
                    found_type = 'hls'
                    
                    if 'audio/mp4' in mime_type or 'audio/aac' in mime_type:
                        metadata['quality'] = 'AAC 128k' 
                        metadata['extension'] = 'm4a'
                    elif 'audio/mpeg' in mime_type:
                        metadata['quality'] = 'MP3 128k'
                        metadata['extension'] = 'mp3'
                    else:
                        metadata['quality'] = 'AAC 128k'
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
    
    metadata['explicit'] = data.get('explicit', False)
    
    # Atur Disc total 1 untuk album
    metadata['totalvolumes'] = "1"
    metadata['totaldiscs'] = "1"
    metadata['discnumber'] = "1"

    metadata['title'] = data.get('title') or 'N/A'
    metadata['artist'] = data.get('user', {}).get('username') or ''
    metadata['albumartist'] = metadata['artist']
    metadata['album'] = metadata['title'] if media_type == 'album' else '' 
    metadata['date'] = (data.get('created_at') or '').split('T')[0]
    metadata['year'] = get_release_year(data)
    
    # Ambil UPC/EAN untuk Album
    metadata['upc'] = data.get('upc_or_ean') or ''
    metadata['barcode'] = metadata['upc']
    metadata['ean'] = metadata['upc']
    
    # Ambil Label untuk Album
    metadata['label'] = data.get('label_name') or ''
    metadata['publisher'] = metadata['label']
    
    art_url_base = data.get('artwork_url') or data.get('user', {}).get('avatar_url')
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
            
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            
            # Warisi data album ke track jika track tidak punya
            if not track_meta.get('album'): track_meta['album'] = metadata['title']
            if not track_meta.get('label'): track_meta['label'] = metadata['label']
            if not track_meta.get('publisher'): track_meta['publisher'] = metadata['publisher']
            
            # Set Total Tracks
            track_meta['totaltracks'] = str(len(tracks_list))
            
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
