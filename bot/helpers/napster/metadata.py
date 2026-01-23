# [GANTI FILE: bot/helpers/napster/metadata.py]

import copy
import re
import aiohttp
import asyncio
import os 
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import napster_manager, NapsterError
from bot.logger import LOGGER

# Pemetaan dari bot Anda ke nilai bitrate Napster
QUALITY_MAP_BITRATE = {
    "FLAC": -1,       # -1 menandakan lossless
    "MP3_320": 320,
    "MP3_192": 192,
    "MP3_128": 128,
    "MP3_64": 64
}

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Napster"""
    url_parsed = urlparse(link)
    parameters = {j:k for j,k in [i.split('=') for i in url_parsed.query.lower().split('&')]} if url_parsed.query else {}
    
    if 'id' in parameters:
        item_types = { 'alb': 'album', 'tra': 'track', 'pp': 'playlist', 'mp': 'playlist', 'art': 'artist' }
        item_type = item_types.get(parameters['id'].split('.')[0])
        if not item_type:
            raise NapsterError(f'URL tidak valid (tipe ID tidak diketahui): {link}')
        return item_type, parameters['id'], {}
    else:
        path_components = url_parsed.path.split('/')
        if 'track' in path_components: item_type = 'track'
        elif 'album' in path_components: item_type = 'album'
        elif 'artist' in path_components: item_type = 'artist'
        elif 'playlist' in path_components: item_type = 'playlist'
        else:
            raise NapsterError(f'URL tidak valid (tipe path tidak diketahui): {link}')

        item_id_str = '/'.join([i for i in path_components if i not in ['', 'track', 'album', 'artist', 'playlist']])
        
        item_id = None
        for comp in reversed(path_components):
             if comp.startswith(('art.', 'alb.', 'tra.', 'ppl.')):
                 item_id = comp
                 break
        
        if not item_id:
             item_id = item_id_str.split('/')[-1]
             LOGGER.warning(f"Napster: URL path tidak mengandung ID eksplisit. Mencoba menggunakan '{item_id}'.")

        return item_type, item_id, {}


async def _process_cover(metadata: dict, album_id: str):
    """Memproses sampul dari ID Album Napster"""
    url = f"https://api.napster.com/imageserver/v2/albums/{album_id}/images/600x600.jpg"
    return await create_cover_file(url, metadata)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    """Memproses metadata untuk satu lagu."""
    client = user['napster_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        if pre_data:
            track_data = pre_data
        else:
            track_data_list = await asyncio.to_thread(client.get_items_list, 'tracks', track_id)
            if not track_data_list:
                raise NapsterError(f"Track {track_id} tidak ditemukan.")
            track_data = track_data_list[0]
            
        if alb_info_pre:
            album_data = alb_info_pre
        else:
            album_data_list = await asyncio.to_thread(client.get_items_list, 'albums', track_data['albumId'])
            if not album_data_list:
                raise NapsterError(f"Album {track_data['albumId']} tidak ditemukan.")
            album_data = album_data_list[0]

    except Exception as e:
        LOGGER.error(f"Napster: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    if not track_data.get('isStreamable', False):
        raise NapsterError(f"Track '{track_data.get('name')}' tidak streamable.")

    metadata['itemid'] = track_id
    
    metadata['title'] = track_data.get('name') or ''
    metadata['album'] = track_data.get('albumName') or ''
    metadata['albumartist'] = album_data.get('artistName') or ''
    
    # --- MODIFIKASI: Menambahkan .zfill(2) agar format menjadi 01, 02, dst ---
    _idx = track_data.get('index')
    metadata['tracknumber'] = str(_idx).zfill(2) if _idx else ''
    # ------------------------------------------------------------------------

    metadata['volume'] = str(track_data.get('disc') or '')
    metadata['totalvolume'] = str(album_data.get('discCount') or '')
    metadata['totaltracks'] = str(album_data.get('trackCount') or '')
    
    release_date = album_data.get('released')
    if release_date:
        metadata['date'] = release_date.split('-')[0]
    
    metadata['copyright'] = album_data.get('copyright') or ''
    metadata['upc'] = album_data.get('upc') or ''
    metadata['isrc'] = track_data.get('isrc') or ''
    
    # Label & Publisher
    if album_data.get('label'):
        metadata['label'] = album_data['label']
        metadata['publisher'] = album_data['label']
    else:
        metadata['label'] = ''
        metadata['publisher'] = ''

    metadata['explicit'] = bool(track_data.get('isExplicit'))
    metadata['provider'] = 'Napster'
    metadata['type'] = 'track'

    # --- PERBAIKAN LOGIKA KONTRIBUTOR (COMPOSER) ---
    artists = [track_data.get('artistName') or '']
    composers = []
    producers = [] 
    
    # Inisialisasi key agar tidak KeyError di set_metadata
    metadata['composer'] = ''
    metadata['producer'] = ''

    if track_data.get('contributors'):
        try:
            # Napster ID -> Nama
            contrib_ids = list(track_data['contributors'].values())
            contrib_data = await asyncio.to_thread(client.get_string_from_items_list, 'artists', contrib_ids, 'name')
            
            # Log untuk debugging (Cek Console saat bot berjalan!)
            LOGGER.info(f"Napster Debug [{track_id}]: Roles ditemukan -> {list(track_data['contributors'].keys())}")

            for role, artist_id in track_data['contributors'].items():
                name = contrib_data.get(artist_id)
                if not name: continue
                
                role_lower = role.lower()
                
                # Artist
                if any(x in role_lower for x in ['primary', 'guest', 'featured']):
                    if name not in artists: artists.append(name)
                
                # Composer (termasuk writer/lyricist jika perlu)
                elif any(x in role_lower for x in ['composer', 'writer', 'lyricist', 'author']):
                    if name not in composers: composers.append(name)
                
                # Producer (termasuk engineer/mixer jika perlu)
                elif any(x in role_lower for x in ['producer', 'engineer', 'mixer', 'remixer']):
                    if name not in producers: producers.append(name)

        except Exception as e:
            LOGGER.warning(f"Napster: Gagal memproses kontributor: {e}")

    # Set ke metadata dict
    metadata['artist'] = ", ".join(artists)
    
    if composers:
        metadata['composer'] = ", ".join(composers)
        LOGGER.info(f"Napster Debug [{track_id}]: Composer set ke -> {metadata['composer']}")
    
    if producers:
        metadata['producer'] = ", ".join(producers)
    # --- BATAS PERBAIKAN ---
    
    # Genre
    if track_data['links'].get('genres'):
        try:
            genre_ids = track_data['links']['genres']['ids']
            genre_data = await asyncio.to_thread(client.get_string_from_items_list, 'genres', genre_ids, 'name')
            metadata['genre'] = ", ".join(list(genre_data.values()))
        except Exception as e:
            LOGGER.warning(f"Napster: Gagal memproses genre: {e}")

    # Sampul
    metadata['cover'] = await _process_cover(metadata, track_data["albumId"])
    metadata['thumbnail'] = metadata['cover']

    # Kualitas
    user_id = user.get('user_id')
    preferred_quality_key = napster_manager.get_user_quality(user_id)
    requested_bitrate = QUALITY_MAP_BITRATE[preferred_quality_key]
    
    if requested_bitrate > client.max_bitrate:
        requested_bitrate = client.max_bitrate
    if requested_bitrate == -1 and not client.hires_enabled:
        requested_bitrate = 320 

    chosen_bitrate = 0
    chosen_codec = ""
    
    if requested_bitrate == -1 and track_data.get('losslessFormats'):
        l_format = track_data['losslessFormats'][0]
        chosen_bitrate = l_format['bitrate']
        chosen_codec = l_format['name'] 
        metadata['quality'] = f"FLAC {l_format['sampleBits']}-bit {l_format['sampleRate']/1000}kHz"
        metadata['extension'] = "flac"
        if chosen_codec == 'MQA':
             metadata['quality'] = f"MQA {l_format['sampleBits']}-bit {l_format['sampleRate']/1000}kHz"

    else:
        effective_bitrate = requested_bitrate if requested_bitrate != -1 else 320
        
        for f in track_data['formats']:
            if f['bitrate'] <= effective_bitrate and f['bitrate'] > chosen_bitrate and f['name'] != 'MQA':
                chosen_bitrate = f['bitrate']
                chosen_codec = f['name']
        
        if chosen_bitrate == 0:
            raise NapsterError(f"Tidak ada bitrate yang cocok ditemukan (diminta <= {effective_bitrate})")
        
        display_codec = "AAC" if chosen_codec != "AAC PLUS" else "HE-AAC"
        metadata['quality'] = f"{display_codec} {chosen_bitrate}k"
        metadata['extension'] = "m4a"

    metadata['download_bitrate'] = chosen_bitrate
    metadata['download_codec'] = chosen_codec
    
    return metadata

# --- BAGIAN PROCESS_ALBUM SAMA SEPERTI SEBELUMNYA (TIDAK PERLU DIUBAH JIKA SUDAH) ---
async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album."""
    client = user['napster_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        album_data_list = await asyncio.to_thread(client.get_items_list, 'albums', album_id)
        if not album_data_list:
            raise NapsterError(f"Album {album_id} tidak ditemukan.")
        album_data = album_data_list[0]
        
        tracks_dict = await asyncio.to_thread(client.get_items_dict, 'albums', album_data['id'], 'tracks', 'tracks', 200)

    except Exception as e:
        LOGGER.error(f"Napster: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    metadata['itemid'] = album_id
    metadata['title'] = album_data.get('name') or ''
    metadata['album'] = album_data.get('name') or ''
    metadata['artist'] = album_data.get('artistName') or ''
    metadata['albumartist'] = album_data.get('artistName') or ''
    
    release_date = album_data.get('released')
    if release_date:
        metadata['date'] = release_date.split('-')[0]
    
    metadata['totaltracks'] = str(album_data.get('trackCount') or '')
    if album_data.get('discCount'):
        metadata['totalvolumes'] = str(album_data.get('discCount'))

    metadata['label'] = album_data.get('label') or ''
    metadata['explicit'] = bool(album_data.get('isExplicit'))
    metadata['provider'] = 'Napster'
    metadata['type'] = 'album'
    
    metadata['cover'] = await _process_cover(metadata, album_data["id"])
    metadata['thumbnail'] = metadata['cover']

    metadata['tracks'] = []
    for track_id, track_data in tracks_dict.items():
        try:
            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=track_data, 
                alb_info_pre=album_data
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"Napster: Gagal memproses track {track_id} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
