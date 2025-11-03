# [GANTI FILE: bot/helpers/deezer/metadata.py]

import copy
from datetime import datetime
import aiohttp
import urllib.parse
import logging # <-- Pastikan logging diimpor

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .dzapi import DeezerAPI 
from bot.logger import LOGGER


async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    # ... (Fungsi ini tetap sama persis seperti sebelumnya) ...
    try:
        if metadata.get('upc') and metadata['upc'] != "0" and metadata['upc'] != "":
            upc_url = f"https://itunes.apple.com/lookup?upc={metadata['upc']}&entity=album&limit=1"
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')

        if metadata.get('albumartist') and metadata.get('album'):
            search_term = urllib.parse.quote(f"{metadata['albumartist']} {metadata['album']}")
            search_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=5"
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        for result in data['results']:
                            itunes_album = result.get('collectionName', '').lower()
                            itunes_artist = result.get('artistName', '').lower()
                            local_album = metadata['album'].lower()
                            local_artist = metadata['albumartist'].lower()
                            
                            if (local_album in itunes_album or itunes_album in local_album) and \
                               (local_artist in itunes_artist):
                                artwork_url = result.get('artworkUrl100')
                                if artwork_url:
                                    return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')
    except Exception as e:
        logging.warning(f"Pencarian sampul iTunes gagal untuk UPC {metadata.get('upc')}: {e}")
        return None
    return None

# --- FUNGSI BARU: Tambahkan pencarian MusicBrainz ---
async def get_musicbrainz_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    """
    Mencoba mengambil URL sampul resolusi tinggi dari MusicBrainz (Cover Art Archive).
    """
    # Header User-Agent yang baik adalah praktik terbaik untuk API MusicBrainz
    headers = {'User-Agent': 'MusicDownloaderBot/1.0 (https://github.com/your-repo)'}
    mbid = None # MusicBrainz Release ID
    
    try:
        # 1. Coba cari berdasarkan UPC (Paling akurat)
        if metadata.get('upc') and metadata['upc'] != "0" and metadata['upc'] != "":
            url = f"https://musicbrainz.org/ws/2/release/?query=barcode:{metadata['upc']}&fmt=json"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('releases') and len(data['releases']) > 0:
                        mbid = data['releases'][0].get('id')
                else:
                    logging.warning(f"MusicBrainz UPC search returned HTTP {resp.status}")

        # 2. Jika tidak ada MBID, coba cari berdasarkan Teks (Kurang akurat)
        if not mbid and metadata.get('albumartist') and metadata.get('album'):
            artist = urllib.parse.quote(metadata['albumartist'])
            album = urllib.parse.quote(metadata['album'])
            url = f"https://musicbrainz.org/ws/2/release/?query=release:{album}%20AND%20artist:{artist}&fmt=json"
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('releases') and len(data['releases']) > 0:
                        # Kita ambil hasil pertama, semoga cocok
                        mbid = data['releases'][0].get('id')
                else:
                    logging.warning(f"MusicBrainz text search returned HTTP {resp.status}")

        # 3. Jika kita punya MBID, ambil sampulnya dari Cover Art Archive
        if mbid:
            art_url = f"https://coverartarchive.org/release/{mbid}"
            async with session.get(art_url, headers=headers, allow_redirects=False) as resp:
                # Jika tidak ada sampul, API akan me-redirect (Status 307)
                if resp.status != 200:
                    logging.warning(f"MusicBrainz CAA: Tidak ada sampul untuk MBID {mbid} (Status: {resp.status})")
                    return None
                    
                art_data = await resp.json()
                for image in art_data.get('images', []):
                    # Cari sampul 'Front'
                    if 'Front' in image.get('types', []) and image.get('thumbnails'):
                        # Ambil 1200px jika ada, jika tidak, ambil gambar asli
                        return image['thumbnails'].get('1200', image.get('image'))
                # Jika tidak ada sampul 'Front', ambil saja gambar pertama yang tersedia
                if art_data.get('images') and art_data['images'][0].get('thumbnails'):
                     return art_data['images'][0]['thumbnails'].get('1200', art_data['images'][0].get('image'))

    except Exception as e:
        logging.warning(f"Pencarian sampul MusicBrainz gagal: {e}")
    
    return None
# --- BATAS FUNGSI BARU ---


async def process_track_metadata(track_id, r_id, cover=None, 
    thumbnail=None, total_tracks=None, album_genre=None, total_disks=None, user: dict = None): 
    
    if not user:
        raise Exception("Fungsi process_track_metadata memerlukan argumen 'user'.")
    deezerapi = user['deezer_api']

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"

    # ... (Panggilan API Deezer tetap sama) ...
    try:
        raw_meta_data = await deezerapi.get_track_data(track_id)
        t_meta = raw_meta_data.get('FALLBACK', raw_meta_data)
    except Exception as e:
        LOGGER.warning(f"Deezer: song.getData gagal untuk {track_id}: {e}")
        t_meta = {} 
    try:
        raw_meta_page = await deezerapi.get_track(track_id)
        t_meta_page = raw_meta_page.get('DATA', {}) 
        t_meta_page = t_meta_page.get('FALLBACK', t_meta_page) 
    except Exception as e:
        LOGGER.error(f"Deezer: deezer.pageTrack gagal total untuk {track_id}: {e}")
        raise Exception(f"Deezer : Track not available (pageTrack API failed)")
    
    # ... (Pengisian metadata dasar tetap sama) ...
    metadata['itemid'] = track_id
    metadata['albumartist'] = t_meta.get('ART_NAME', t_meta_page.get('ART_NAME', ''))
    metadata['album'] = t_meta.get('ALB_TITLE', t_meta_page.get('ALB_TITLE', ''))
    metadata['upc'] = t_meta.get('UPC', t_meta_page.get('UPC', ''))
    # ... (Sisa metadata tetap sama) ...
    metadata['artist'] = get_artists_name(t_meta)
    if not metadata['artist']:
        metadata['artist'] = get_artists_name(t_meta_page)
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'track'
    
    # --- MODIFIKASI: Logika Sampul Baru (iTunes -> MusicBrainz -> Deezer -> Lokal) ---
    cover_id = t_meta.get('ALB_PICTURE', t_meta_page.get('ALB_PICTURE', ''))

    if cover:
        # Jika sampul disediakan (dari album), gunakan itu
        metadata['cover'] = cover
    else:
        # Jika ini track mandiri, cari sampulnya
        cover_url = None
        try:
            async with aiohttp.ClientSession() as session:
                # 1. Coba iTunes
                logging.debug(f"Mencari sampul di iTunes untuk {metadata['album']}...")
                cover_url = await get_itunes_cover_url(metadata, session)
                
                # 2. Coba MusicBrainz
                if not cover_url:
                    logging.debug(f"iTunes gagal, mencari sampul di MusicBrainz...")
                    cover_url = await get_musicbrainz_cover_url(metadata, session)
        except Exception as e:
            logging.warning(f"Sesi pencarian sampul pihak ketiga gagal (track): {e}")

        # 3. Coba Deezer (jika 1 & 2 gagal)
        if not cover_url and cover_id:
            logging.debug(f"Pihak ketiga gagal, menggunakan sampul Deezer.")
            cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/3000x0-none-100-0-0.png'

        # 4. Kirim URL terbaik (atau None) ke create_cover_file
        # create_cover_file akan menangani fallback lokal './project-siesta.png'
        metadata['cover'] = await create_cover_file(cover_url, metadata)

    if thumbnail:
        metadata['thumbnail'] = thumbnail
    else:
        # Selalu gunakan sampul Deezer untuk thumbnail cepat
        metadata['thumbnail'] = await get_cover(cover_id, metadata, True)
    # --- BATAS MODIFIKASI ---

    metadata['token'] = t_meta_page['TRACK_TOKEN']
    metadata['token_expiry'] = t_meta_page['TRACK_TOKEN_EXPIRE']
    
    metadata['quality'] = await get_quality(t_meta_page, deezerapi)
    return metadata
            

async def process_album_metadata(album_id:int, a_meta:dict, t_meta:list, r_id, user: dict = None):
    if not user:
        raise Exception("Fungsi process_album_metadata memerlukan argumen 'user'.")
    deezerapi = user['deezer_api']

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # ... (Pengisian metadata dasar tetap sama) ...
    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta.get('ART_NAME', '')
    metadata['upc'] = a_meta.get('UPC', '')
    metadata['title'] = a_meta.get('ALB_TITLE', 'Unknown Album')
    metadata['album'] = a_meta.get('ALB_TITLE', 'Unknown Album')
    metadata['artist'] = get_artists_name(a_meta) 
    # ... (Sisa metadata tetap sama) ...
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'
    
    # --- MODIFIKASI: Logika Sampul Baru (iTunes -> MusicBrainz -> Deezer -> Lokal) ---
    cover_id = a_meta.get('ALB_PICTURE', '')
    cover_url = None
    
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Coba iTunes
            logging.debug(f"Mencari sampul di iTunes untuk {metadata['album']}...")
            cover_url = await get_itunes_cover_url(metadata, session)
            
            # 2. Coba MusicBrainz
            if not cover_url:
                logging.debug(f"iTunes gagal, mencari sampul di MusicBrainz...")
                cover_url = await get_musicbrainz_cover_url(metadata, session)
    except Exception as e:
        logging.warning(f"Sesi pencarian sampul pihak ketiga gagal (album): {e}")

    # 3. Coba Deezer (jika 1 & 2 gagal)
    if not cover_url and cover_id:
        logging.debug(f"Pihak ketiga gagal, menggunakan sampul Deezer.")
        cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/3000x0-none-100-0-0.png'

    # 4. Kirim URL terbaik (atau None) ke create_cover_file
    # create_cover_file akan menangani fallback lokal './project-siesta.png'
    # Log 'Gagal mengunduh' - [2025-11-03 23:43:21,254]...] dan 'Cover art tidak ditemukan' - [2025-11-03 23:43:31,203]...]
    # berasal dari dalam create_cover_file, jadi logika ini sudah benar.
    metadata['cover'] = await create_cover_file(cover_url, metadata)
    
    # Selalu gunakan sampul Deezer untuk thumbnail cepat
    metadata['thumbnail'] = await get_cover(cover_id, metadata, True)
    # --- BATAS MODIFIKASI ---
        
    metadata['tracks'] = []
    for track in t_meta['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], 
                r_id,
                metadata['cover'], # <-- Ini akan meneruskan sampul resolusi tinggi ke setiap track
                metadata['thumbnail'],
                metadata['totaltracks'],
                album_genre_name, 
                metadata['totalvolume'],
                user=user
            )
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"Gagal memproses metadata untuk track ID {track.get('SNG_ID')}: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata



async def process_playlist_meta(raw_meta, r_id, user: dict = None):
    # ... (Fungsi ini tetap sama, sampul playlist tidak dicari di pihak ketiga) ...
    if not user:
        raise Exception("Fungsi process_playlist_meta memerlukan argumen 'user'.")
    deezerapi = user['deezer_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['title'] = raw_meta['DATA']['TITLE']
    metadata['duration'] = raw_meta['DATA']['DURATION']
    metadata['totaltracks'] = raw_meta['DATA']['NB_SONG'] 
    metadata['itemid'] = raw_meta['DATA']['PLAYLIST_ID']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Deezer'
    metadata['cover'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata, True)
    if raw_meta['DATA'].get('CREATOR') and raw_meta['DATA']['CREATOR'].get('NAME'):
        metadata['artist'] = raw_meta['DATA']['CREATOR']['NAME']
    for track in raw_meta['SONGS']['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], 
                r_id,
                total_tracks=metadata['totaltracks'],
                user=user 
            )
        except:
            continue
        metadata['tracks'].append(track_meta)
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
    else:
        metadata['quality'] = "N/A"
    return metadata


def get_artists_name(meta:dict):
    # ... (Fungsi ini tetap sama) ...
    artists = []
    if meta.get('ARTISTS'):
        for a in meta['ARTISTS']:
            artists.append(a['ART_NAME'])
    elif meta.get('ART_NAME'):
        artists.append(meta.get('ART_NAME'))
    return ', '.join([str(artist) for artist in artists if artist])


async def get_cover(cover_id, meta:dict, thumbnail=False):
    # ... (Fungsi ini tetap sama) ...
    url = None
    if cover_id:
        url = (
            f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/3000x0-none-100-0-0.png'
            if not thumbnail
            else f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/80x0-none-100-0-0.png'
        )
    return await create_cover_file(url, meta, thumbnail)


async def get_quality(meta:dict, deezerapi: DeezerAPI):
    # ... (Fungsi ini tetap sama) ...
    format = 'FLAC'
    premium_formats = ['FLAC', 'MP3_320']
    countries = meta.get('AVAILABLE_COUNTRIES', {}).get('STREAM_ADS')
    if not countries:
        raise Exception("Deezer : Track not available")
    elif deezerapi.country not in countries:
        raise Exception("Deezer : Track not available in your country")
    else:
        formats_to_check = premium_formats
        while len(formats_to_check) != 0:
            if formats_to_check[0] != format:
                formats_to_check.pop(0)
            else:
                break
        temp_f = None
        for f in formats_to_check:
            if f'FILESIZE_{f}' in meta and meta[f'FILESIZE_{f}'] != '0':
                temp_f = f
                break
        if temp_f is None:
            temp_f = 'MP3_128'
        format = temp_f
        if format not in deezerapi.available_formats:
            raise Exception("Deezer : Format not available by your subscription")
    return format
