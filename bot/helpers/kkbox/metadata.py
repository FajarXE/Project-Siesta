# [GANTI FILE: bot/helpers/kkbox/metadata.py]

import copy
import re
import aiohttp
import asyncio
import logging
import os 
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import kkbox_manager, KKBoxError
from bot.logger import LOGGER

QUALITY_MAP_DISPLAY = {
    "128k": ("MP3 128k", "mp3"),
    "192k": ("MP3 192k", "mp3"),
    "320k": ("AAC 320k", "m4a"),
    "hifi": ("FLAC 16-bit", "flac"),
    "hires": ("FLAC 24-bit", "flac")
}
QUALITY_ORDER = ["hires", "hifi", "320k", "192k", "128k"]

def custom_url_parse(link: str):
    url = urlparse(link)
    path_match = None
    if url.hostname == 'play.kkbox.com':
        path_match = re.match(r'^\/(track|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
    elif url.hostname == 'www.kkbox.com':
        path_match = re.match(r'^\/[a-z]{2}\/[a-z]{2}\/(song|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
    else:
        raise KKBoxError(f'URL tidak valid: {link}')
    if not path_match:
        raise KKBoxError(f'URL tidak valid: {link}')
    
    type = path_match.group(1)
    if type == 'song': type = 'track'
    
    return type, path_match.group(2), {}

async def _process_cover(metadata: dict, url_template: str):
    size = 1400
    file_type = "jpg"
    
    url = url_template
    if not url: return None 

    if size > 2048:
        url = url.replace('fit/{width}x{height}', 'original')
        url = url.replace('cropresize/{width}x{height}', 'original')
    else:
        url = url.replace('{width}', str(size))
        url = url.replace('{height}', str(size))
    url = url.replace('{format}', file_type)
    
    return await create_cover_file(url, metadata)

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    """Memproses metadata untuk satu lagu."""
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        if pre_data:
            track_data = pre_data
        else:
            songs_list = await asyncio.to_thread(client.get_songs, [track_id])
            if not songs_list:
                raise KKBoxError(f"Track {track_id} tidak ditemukan.")
            track_data = songs_list[0]

        if alb_info_pre:
            alb_info = alb_info_pre
        else:
            # Fallback jika tidak ada info album pre-loaded
            album_raw_id = track_data.get('raw_album_id') or int(track_data['album_id'])
            
            try:
                album_data_more = await asyncio.to_thread(client.get_album_more, album_raw_id)
                if not album_data_more or 'info' not in album_data_more:
                    raise KKBoxError("Invalid get_album_more response")
                alb_info = album_data_more['info']
                alb_info['num_tracks'] = len(album_data_more.get('song_list', {}).get('song', []))
            except Exception as e:
                # LOGGER.warning(f"KKBox: Fallback album info from track data.")
                alb_obj = track_data.get('album', {})
                alb_info = {
                    'album_name': alb_obj.get('name', 'Unknown Album'),
                    'artist_name': alb_obj.get('artist', {}).get('name', 'Unknown Artist'),
                    'album_date': track_data.get('release_date') or alb_obj.get('release_date', ''),
                    'num_tracks': 1, 
                    'album_photo_info': {'url_template': alb_obj.get('images', [{}])[0].get('url', '')}
                }

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('song_name') or track_data.get('text') or track_data.get('name')
    
    artists = []
    if 'artist_role' in track_data:
        if 'mainartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['mainartist_list']['mainartist'])
        if 'featuredartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['featuredartist_list']['featuredartist'])
    
    metadata['albumartist'] = alb_info.get('artist_name', 'Unknown Artist')
    
    if not artists:
        if 'artist' in track_data and 'name' in track_data['artist']:
             artists = [track_data['artist']['name']]
        else:
             artists = [metadata['albumartist']]
    
    metadata['artist'] = ", ".join(artists)
    metadata['album'] = alb_info.get('album_name', 'Unknown Album')
    
    # Prioritaskan Tanggal dari Track jika tersedia
    t_date = track_data.get('release_date')
    a_date = alb_info.get('album_date')
    
    if t_date and len(t_date) > len(str(a_date or "")):
         metadata['date'] = t_date
    else:
         metadata['date'] = a_date
         
    metadata['year'] = metadata['date'][:4] if metadata['date'] else ""

    metadata['tracknumber'] = str(track_data.get('song_idx', 1))
    metadata['totaltracks'] = str(alb_info.get('num_tracks', 1))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    
    metadata['genre'] = track_data.get('genre_name')
    metadata['explicit'] = bool(track_data.get('song_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'track'
    
    cover_template = ""
    if 'album_photo_info' in track_data:
        cover_template = track_data['album_photo_info']['url_template']
    elif 'images' in track_data.get('album', {}):
        cover_template = track_data['album']['images'][0]['url']
    elif 'album_photo_info' in alb_info:
        cover_template = alb_info['album_photo_info']['url_template']

    if cover_template:
        metadata['cover'] = await _process_cover(metadata, cover_template)
        metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    user_id = user.get('user_id')
    preferred_quality = kkbox_manager.get_user_quality(user_id)
    user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    
    chosen_quality_key = None
    avail_q = track_data.get('audio_quality', {})
    
    for q_key in user_quality_order:
        if q_key in avail_q and q_key in client.available_qualities:
            chosen_quality_key = q_key
            break
            
    if not chosen_quality_key:
        for q_key in reversed(QUALITY_ORDER):
             if q_key in avail_q and q_key in client.available_qualities:
                chosen_quality_key = q_key
                break

    if not chosen_quality_key:
        raise KKBoxError(f"Tidak ada kualitas yang kompatibel untuk track {track_id}")

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_quality_key]
    
    dl_id = track_data.get('id')
    if 'song_more_url' in track_data:
         dl_id = track_data['song_more_url'].split('/')[-1]
         
    metadata['download_id'] = dl_id
    metadata['download_quality_key'] = chosen_quality_key
    
    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """
    Memproses metadata untuk satu album.
    Memaksa pencarian tanggal rilis jika data V1 tidak lengkap.
    """
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    alb_info = None
    tracks_list = []
    is_fallback_mode = False

    try:
        # 1. Ambil info dasar (V1 API)
        album_resp = await asyncio.to_thread(client.get_album, album_id)
        v1_data = album_resp.get('album') if 'album' in album_resp else album_resp
        if not v1_data: raise KKBoxError("Respons get_album (V1) kosong.")

        # 2. Coba ambil info detail (Legacy API)
        raw_id = v1_data.get('album_id') or v1_data.get('id')
        try:
            album_data_more = await asyncio.to_thread(client.get_album_more, raw_id)
            if album_data_more and 'info' in album_data_more and 'song_list' in album_data_more:
                alb_info = album_data_more['info']
                tracks_list = album_data_more['song_list']['song']
                alb_info['num_tracks'] = len(tracks_list)
            else:
                LOGGER.warning(f"KKBox: Legacy API invalid untuk {album_id}. Menggunakan Fallback.")
        except Exception:
             LOGGER.warning(f"KKBox: Legacy API Error. Menggunakan Fallback.")

        # 3. Fallback Construction
        if not alb_info:
            is_fallback_mode = True
            raw_tracks = v1_data.get('tracks', {})
            if isinstance(raw_tracks, dict) and 'data' in raw_tracks:
                data_tracks = raw_tracks['data']
            elif isinstance(raw_tracks, list):
                data_tracks = raw_tracks
            else:
                data_tracks = []

            alb_info = {
                'album_name': v1_data.get('name'),
                'artist_name': v1_data.get('artist', {}).get('name'),
                'album_date': v1_data.get('release_date', ''),
                'album_is_explicit': v1_data.get('explicit', False),
                'album_photo_info': {
                    'url_template': v1_data.get('images', [{}])[0].get('url', '')
                }
            }
            
            # Buat list track dasar
            for rt in data_tracks:
                if 'id' in rt:
                    rt['song_more_url'] = f"https://kkbox.com/song/{rt['id']}"
                    if 'artist' not in rt: 
                        rt['artist'] = {'name': alb_info['artist_name']}
                    tracks_list.append(rt)
            alb_info['num_tracks'] = len(tracks_list)

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    # --- BAGIAN KRUSIAL: PERBAIKAN TANGGAL (Brute Force Check) ---
    current_date = alb_info.get('album_date', '')
    
    # Jika tanggal kosong ATAU panjangnya kurang dari 10 (misal "2025-08"), kita cari yang lengkap
    if not current_date or len(current_date) < 10:
        LOGGER.info(f"KKBox: Tanggal album tidak lengkap ('{current_date}'). Mencari di detail lagu...")
        
        # Cek track pertama (biasanya cukup)
        if tracks_list:
            try:
                # Ambil ID track pertama
                first_track_id = None
                if 'id' in tracks_list[0]:
                    first_track_id = tracks_list[0]['id']
                elif 'song_more_url' in tracks_list[0]:
                    first_track_id = tracks_list[0]['song_more_url'].split('/')[-1]
                
                if first_track_id:
                    # Request Metadata V2 untuk track ini
                    track_details = await asyncio.to_thread(client.get_songs, [first_track_id])
                    
                    if track_details:
                        t_meta = track_details[0]
                        
                        # Cek tanggal di berbagai tempat
                        date_candidates = []
                        if t_meta.get('release_date'): 
                            date_candidates.append(t_meta['release_date'])
                        if t_meta.get('album', {}).get('release_date'): 
                            date_candidates.append(t_meta['album']['release_date'])
                            
                        # Urutkan dari yang terpanjang (YYYY-MM-DD > YYYY-MM)
                        full_dates = [d for d in date_candidates if len(d) >= 10]
                        
                        if full_dates:
                            new_date = full_dates[0]
                            alb_info['album_date'] = new_date
                            LOGGER.info(f"KKBox: DITEMUKAN Tanggal Lengkap: {new_date}")
                        else:
                            LOGGER.warning("KKBox: Tidak ada tanggal lengkap ditemukan di track V2.")
            except Exception as e:
                LOGGER.error(f"KKBox: Gagal mencari tanggal track: {e}")
    # -------------------------------------------------------------

    metadata['itemid'] = album_id
    metadata['title'] = alb_info.get('album_name')
    metadata['album'] = alb_info.get('album_name')
    metadata['artist'] = alb_info.get('artist_name')
    metadata['albumartist'] = alb_info.get('artist_name')
    
    metadata['date'] = alb_info.get('album_date')
    metadata['year'] = metadata['date'][:4] if metadata['date'] else ""
    
    metadata['totaltracks'] = str(alb_info.get('num_tracks', 1))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    metadata['explicit'] = bool(alb_info.get('album_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'album'
    
    cover_template = alb_info['album_photo_info']['url_template']
    metadata['cover'] = await _process_cover(metadata, cover_template)
    metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    metadata['tracks'] = []
    for song_data in tracks_list:
        try:
            track_id = song_data['song_more_url'].split('/')[-1]
            # Kirim alb_info yang sudah diperbaiki tanggalnya ke process_track_metadata
            use_pre_data = None if is_fallback_mode else song_data

            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=use_pre_data, 
                alb_info_pre=alb_info 
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal memproses track {song_data.get('song_more_url', 'Unknown')} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
