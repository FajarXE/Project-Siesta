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

# Kualitas dari interface.py
QUALITY_MAP_DISPLAY = {
    "128k": ("MP3 128k", "mp3"),
    "192k": ("MP3 192k", "mp3"),
    "320k": ("AAC 320k", "m4a"),
    "hifi": ("FLAC 16-bit", "flac"),
    "hires": ("FLAC 24-bit", "flac")
}
# Urutan prioritas kualitas
QUALITY_ORDER = ["hires", "hifi", "320k", "192k", "128k"]

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL KKBox (dari interface.py)"""
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
    """Memproses sampul dari URL template KKBox"""
    size = 1400 # Ukuran default yang bagus
    file_type = "jpg" # KKBox tampaknya menggunakan jpg/png
    
    url = url_template
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
        # Panggil API di thread terpisah
        if pre_data:
            track_data = pre_data
        else:
            songs_list = await asyncio.to_thread(client.get_songs, [track_id])
            if not songs_list:
                raise KKBoxError(f"Track {track_id} tidak ditemukan (get_songs empty).")
            track_data = songs_list[0]

        # Dapatkan info album
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
                LOGGER.warning(f"KKBox (Track): Gagal fetch album info via legacy API: {e}. Mencoba fallback ke data track.")
                # Fallback minimal menggunakan data yang ada di track_data (jika tersedia)
                # track_data dari get_songs (V2) biasanya memiliki objek 'album'
                if 'album' in track_data:
                    alb_obj = track_data['album']
                    alb_info = {
                        'album_name': alb_obj.get('name', 'Unknown Album'),
                        'artist_name': alb_obj.get('artist', {}).get('name', 'Unknown Artist'),
                        'album_date': alb_obj.get('release_date', ''),
                        'num_tracks': 1, # Tidak bisa tahu total tracks
                        'album_photo_info': {'url_template': alb_obj.get('images', [{}])[0].get('url', '')}
                    }
                else:
                    raise e

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('song_name') or track_data.get('text') or track_data.get('name')
    
    # Logika artis
    artists = []
    if 'artist_role' in track_data:
        if 'mainartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['mainartist_list']['mainartist'])
        if 'featuredartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['featuredartist_list']['featuredartist'])
    
    metadata['albumartist'] = alb_info.get('artist_name', 'Unknown Artist')
    
    if not artists:
        # Coba ambil dari root object jika structure beda
        if 'artist' in track_data and 'name' in track_data['artist']:
             artists = [track_data['artist']['name']]
        else:
             artists = [metadata['albumartist']]
    
    metadata['artist'] = ", ".join(artists)
    metadata['album'] = alb_info.get('album_name', 'Unknown Album')
    metadata['date'] = alb_info.get('album_date', '')
    metadata['tracknumber'] = str(track_data.get('song_idx', 1))
    metadata['totaltracks'] = str(alb_info.get('num_tracks', 1))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    
    metadata['genre'] = track_data.get('genre_name')
    metadata['explicit'] = bool(track_data.get('song_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'track'
    
    # Sampul
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

    # --- LOGIKA KUALITAS ---
    user_id = user.get('user_id')
    preferred_quality = kkbox_manager.get_user_quality(user_id)
    user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    
    chosen_quality_key = None
    
    # Pastikan audio_quality tersedia
    avail_q = track_data.get('audio_quality', {})
    if not avail_q:
         # Coba fallback ke properti lain jika ada (jarang terjadi di V2)
         pass

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
    
    # Simpan info unduhan
    # V2 song object punya 'song_more_url', ambil ID dari sana atau gunakan ID langsung
    dl_id = track_data.get('id')
    if 'song_more_url' in track_data:
         dl_id = track_data['song_more_url'].split('/')[-1]
         
    metadata['download_id'] = dl_id
    metadata['download_quality_key'] = chosen_quality_key
    
    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album (dengan Fallback V1)."""
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    alb_info = None
    tracks_list = []
    is_fallback_mode = False

    try:
        # 1. Ambil info dasar (V1 API) - Ini biasanya berhasil
        album_resp = await asyncio.to_thread(client.get_album, album_id)
        
        # Cek struktur respons V1
        v1_data = album_resp.get('album') if 'album' in album_resp else album_resp
        if not v1_data:
             raise KKBoxError("Respons get_album (V1) kosong.")

        # 2. Coba ambil info detail (Legacy API) - Ini yang sering gagal
        raw_id = v1_data.get('album_id') or v1_data.get('id')
        
        # --- BLOK COBA GET_ALBUM_MORE ---
        try:
            # Gunakan try-except khusus untuk endpoint ini
            album_data_more = await asyncio.to_thread(client.get_album_more, raw_id)

            if album_data_more and 'info' in album_data_more and 'song_list' in album_data_more:
                alb_info = album_data_more['info']
                tracks_list = album_data_more['song_list']['song']
            else:
                LOGGER.warning(f"KKBox: Respons 'get_album_more' invalid untuk {album_id}. Beralih ke fallback V1.")
        except Exception as e_more:
             LOGGER.warning(f"KKBox: Gagal akses 'get_album_more' ({e_more}). Beralih ke fallback V1.")
        # --- AKHIR BLOK ---

        # 3. Fallback Logic: Jika alb_info masih kosong, gunakan data V1
        if not alb_info:
            is_fallback_mode = True
            LOGGER.info(f"KKBox: Menggunakan metadata Fallback (V1) untuk album {album_id}")
            
            # Konstruksi alb_info dari V1 data
            alb_info = {
                'album_name': v1_data.get('name'),
                'artist_name': v1_data.get('artist', {}).get('name'),
                'album_date': v1_data.get('release_date'),
                'album_is_explicit': v1_data.get('explicit', False),
                # Ambil gambar terbesar
                'album_photo_info': {
                    'url_template': v1_data.get('images', [{}])[0].get('url', '')
                }
            }
            
            # Ambil tracks dari V1
            raw_tracks = v1_data.get('tracks', {}).get('data', [])
            for rt in raw_tracks:
                # Mock song_more_url karena handler mengharapkannya untuk ekstraksi ID
                # Atau pastikan ID tersedia
                if 'id' in rt:
                    rt['song_more_url'] = f"https://kkbox.com/song/{rt['id']}"
                    tracks_list.append(rt)
            
            alb_info['num_tracks'] = len(tracks_list)

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    # Validasi akhir
    if not alb_info or not tracks_list:
        raise Exception(f"Gagal mengumpulkan metadata album KKBox (Mode Fallback: {is_fallback_mode})")

    metadata['itemid'] = album_id
    metadata['title'] = alb_info.get('album_name')
    metadata['album'] = alb_info.get('album_name')
    metadata['artist'] = alb_info.get('artist_name')
    metadata['albumartist'] = alb_info.get('artist_name')
    metadata['date'] = alb_info.get('album_date')
    metadata['totaltracks'] = str(alb_info.get('num_tracks'))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    metadata['explicit'] = bool(alb_info.get('album_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'album'
    
    # Sampul
    cover_template = alb_info['album_photo_info']['url_template']
    metadata['cover'] = await _process_cover(metadata, cover_template)
    metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    metadata['tracks'] = []
    for song_data in tracks_list:
        try:
            # Ekstrak ID
            track_id = song_data['song_more_url'].split('/')[-1]
            
            # PENTING: Jika mode fallback, 'song_data' (dari V1) mungkin tidak lengkap
            # untuk process_track_metadata (yang mengharapkan struktur V2/Legacy).
            # Jadi kita kirim pre_data=None agar process_track_metadata mengambil data fresh (V2).
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
