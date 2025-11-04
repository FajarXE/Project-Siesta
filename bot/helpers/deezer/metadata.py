# [GANTI FILE: bot/helpers/deezer/metadata.py]

import copy
from datetime import datetime
import aiohttp
import urllib.parse
import logging
import os # <-- Impor OS
from config import Config # <-- Impor Config

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .dzapi import DeezerAPI 
from bot.logger import LOGGER

# --- MODIFIKASI: Path fallback yang sudah diperbaiki ---
FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")
# --- BATAS MODIFIKASI ---


async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    """
    Mencoba mengambil URL sampul resolusi tinggi dari iTunes menggunakan UPC atau pencarian Teks.
    """
    try:
        # 1. Coba cari via UPC (Paling Akurat)
        if metadata.get('upc') and metadata['upc'] != "0" and metadata['upc'] != "":
            upc_url = f"https://itunes.apple.com/lookup?upc={metadata['upc']}&entity=album&limit=1"
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            return artwork_url.replace('100x100bb.jpg', '1200x1200bb.jpg')

        # 2. Jika UPC gagal/tidak ada, coba cari via Teks (Album Artist + Album Title)
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


async def process_track_metadata(track_id, r_id, cover=None, 
    thumbnail=None, total_tracks=None, album_genre=None, total_disks=None, user: dict = None): 
    
    if not user:
        raise Exception("Fungsi process_track_metadata memerlukan argumen 'user'.")
    deezerapi = user['deezer_api']

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"

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
    
    metadata['itemid'] = track_id
    metadata['albumartist'] = t_meta.get('ART_NAME', t_meta_page.get('ART_NAME', ''))
    metadata['album'] = t_meta.get('ALB_TITLE', t_meta_page.get('ALB_TITLE', ''))
    metadata['upc'] = t_meta.get('UPC', t_meta_page.get('UPC', ''))
    metadata['artist'] = get_artists_name(t_meta)
    if not metadata['artist']:
        metadata['artist'] = get_artists_name(t_meta_page)
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'track'
    metadata['copyright'] = t_meta.get('COPYRIGHT', t_meta_page.get('COPYRIGHT', ''))
    metadata['isrc'] = t_meta.get('ISRC', t_meta_page.get('ISRC', ''))
    metadata['title'] = t_meta.get('SNG_TITLE', t_meta_page.get('SNG_TITLE', ''))
    if t_meta.get('VERSION'):
        metadata['title'] += f' ({t_meta["VERSION"]})'
    elif t_meta_page.get('VERSION'):
         metadata['title'] += f' ({t_meta_page["VERSION"]})'
    metadata['title'] = metadata['title'].replace('/', ' ')
    metadata['duration'] = t_meta.get('DURATION', t_meta_page.get('DURATION', 0))
    try:
        explicit_data = t_meta.get('EXPLICIT_TRACK_CONTENT')
        if not explicit_data:
            explicit_data = t_meta_page.get('EXPLICIT_TRACK_CONTENT', {})
        explicit_status = explicit_data.get('EXPLICIT_LYRICS_STATUS', 0)
        metadata['explicit'] = True if explicit_status == 1 else False
    except Exception:
        metadata['explicit'] = False 
    metadata['tracknumber'] = t_meta.get('TRACK_NUMBER', t_meta_page.get('TRACK_NUMBER', '1'))
    if total_tracks:
        metadata['totaltracks'] = total_tracks
    metadata['date'] = t_meta.get('PHYSICAL_RELEASE_DATE', t_meta_page.get('PHYSICAL_RELEASE_DATE', ''))
    if album_genre:
        metadata['genre'] = album_genre
    elif t_meta_page.get('GENRE_NAME'): 
         metadata['genre'] = t_meta_page['GENRE_NAME']
    metadata['volume'] = str(t_meta.get('DISK_NUMBER', t_meta_page.get('DISK_NUMBER', '1')))
    if total_disks:
        metadata['totalvolume'] = str(total_disks)
    if t_meta.get('CONTRIBUTORS'): 
        composers = []
        for contributor in t_meta['CONTRIBUTORS']:
            role_id = str(contributor.get('ROLE_ID'))
            if role_id in ['1', '4', '5']: 
                composers.append(contributor.get('ART_NAME'))
        if composers:
            metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))
    
    cover_id = t_meta.get('ALB_PICTURE', t_meta_page.get('ALB_PICTURE', ''))
    
    if cover:
        metadata['cover'] = cover
    else:
        cover_url = None
        try:
            async with aiohttp.ClientSession() as session:
                logging.debug(f"Mencari sampul di iTunes untuk {metadata['album']}...")
                cover_url = await get_itunes_cover_url(metadata, session)
        except Exception as e:
            logging.warning(f"Sesi pencarian sampul iTunes gagal (track): {e}")

        if not cover_url and cover_id:
            logging.debug(f"iTunes gagal, menggunakan sampul Deezer.")
            cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png'
        
        final_cover_path_or_url = cover_url
        if not cover_url:
            if os.path.exists(FALLBACK_IMAGE_PATH):
                logging.warning(f"Semua sumber online gagal, menggunakan fallback lokal: {FALLBACK_IMAGE_PATH}")
                final_cover_path_or_url = FALLBACK_IMAGE_PATH
            else:
                logging.error(f"SEMUA SUMBER GAGAL, dan fallback lokal TIDAK DITEMUKAN di {FALLBACK_IMAGE_PATH}")

        metadata['cover'] = await create_cover_file(final_cover_path_or_url, metadata)

    if thumbnail:
        metadata['thumbnail'] = thumbnail
    else:
        metadata['thumbnail'] = await get_cover(cover_id, metadata, True)

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
    
    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta.get('ART_NAME', '')
    metadata['upc'] = a_meta.get('UPC', '')
    metadata['title'] = a_meta.get('ALB_TITLE', 'Unknown Album')
    metadata['album'] = a_meta.get('ALB_TITLE', 'Unknown Album')
    metadata['artist'] = get_artists_name(a_meta) 
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'
    if a_meta.get('VERSION'):
        metadata['title'] += f' ({a_meta["VERSION"]})'
    metadata['date'] = a_meta.get('DIGITAL_RELEASE_DATE', '')
    metadata['totaltracks'] = a_meta.get('NUMBER_TRACK', '0')
    metadata['duration'] = a_meta.get('DURATION', 0)
    metadata['copyright'] = a_meta.get('COPYRIGHT', '')
    metadata['explicit'] = a_meta.get('explicit_lyrics', False)
    album_genre_name = ''
    if a_meta.get('genres') and a_meta.get('genres').get('data'):
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
            metadata['genre'] = album_genre_name
    metadata['totalvolume'] = str(a_meta.get('DISK_COUNT', '1'))
    
    
    cover_id = a_meta.get('ALB_PICTURE', '')
    cover_url = None
    
    try:
        async with aiohttp.ClientSession() as session:
            logging.debug(f"Mencari sampul di iTunes untuk {metadata['album']}...")
            cover_url = await get_itunes_cover_url(metadata, session)
    except Exception as e:
        logging.warning(f"Sesi pencarian sampul iTunes gagal (album): {e}")

    if not cover_url and cover_id:
        logging.debug(f"iTunes gagal, menggunakan sampul Deezer.")
        cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png'

    final_cover_path_or_url = cover_url
    if not cover_url:
        if os.path.exists(FALLBACK_IMAGE_PATH):
            logging.warning(f"Semua sumber online gagal, menggunakan fallback lokal: {FALLBACK_IMAGE_PATH}")
            final_cover_path_or_url = FALLBACK_IMAGE_PATH
        else:
            logging.error(f"SEMUA SUMBER GAGAL, dan fallback lokal TIDAK DITEMUKAN di {FALLBACK_IMAGE_PATH}")

    metadata['cover'] = await create_cover_file(final_cover_path_or_url, metadata)
    
    metadata['thumbnail'] = await get_cover(cover_id, metadata, True)
        
    metadata['tracks'] = []
    for track in t_meta['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], 
                r_id,
                metadata['cover'], 
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
    artists = []
    if meta.get('ARTISTS'):
        for a in meta['ARTISTS']:
            artists.append(a['ART_NAME'])
    elif meta.get('ART_NAME'):
        artists.append(meta.get('ART_NAME'))
    return ', '.join([str(artist) for artist in artists if artist])


async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (
            f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png'
            if not thumbnail
            else f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/80x0-none-100-0-0.png'
        )
    return await create_cover_file(url, meta, thumbnail)


async def get_quality(meta:dict, deezerapi: DeezerAPI):
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
