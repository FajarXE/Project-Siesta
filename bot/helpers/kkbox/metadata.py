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
            track_data = songs_list[0]
            
        # Dapatkan info album
        if alb_info_pre:
            alb_info = alb_info_pre
        else:
            album_raw_id = track_data.get('raw_album_id') or int(track_data['album_id'])
            album_data_more = await asyncio.to_thread(client.get_album_more, album_raw_id)
            alb_info = album_data_more['info']
            alb_info['num_tracks'] = len(album_data_more['song_list']['song'])

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('song_name') or track_data['text']
    
    # Logika artis dari interface.py
    artists = []
    if 'mainartist_list' in track_data['artist_role']:
        artists.extend(track_data['artist_role']['mainartist_list']['mainartist'])
    if 'featuredartist_list' in track_data['artist_role']:
        artists.extend(track_data['artist_role']['featuredartist_list']['featuredartist'])
    
    # --- MODIFIKASI DIMULAI (PERBAIKAN ARTIS TIDAK DIKETAHUI) ---
    # Ambil artis album TERLEBIH DAHULU
    metadata['albumartist'] = alb_info['artist_name']
    
    # Cek jika daftar 'artists' (artis lagu) kosong
    if not artists:
        # Jika kosong, gunakan 'albumartist' sebagai fallback
        LOGGER.debug(f"KKBox: Artis lagu tidak ditemukan untuk '{metadata['title']}', menggunakan artis album: {metadata['albumartist']}")
        artists = [metadata['albumartist']]
    
    metadata['artist'] = ", ".join(artists) # Sekarang dijamin memiliki nilai
    # --- MODIFIKASI SELESAI ---
    
    metadata['album'] = alb_info['album_name']
    metadata['date'] = alb_info['album_date']
    metadata['tracknumber'] = str(track_data['song_idx'])
    metadata['totaltracks'] = str(alb_info['num_tracks'])
    
    # --- TAMBAHAN: Mengambil Total Volume (Disk) ---
    # Kita asumsikan API key-nya adalah 'num_volumes', default ke 1
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    # --- BATAS TAMBAHAN ---
    
    metadata['genre'] = track_data.get('genre_name')

    # --- TAMBAHAN BARU: Mengambil Composer ---
    composer_list = []
    # Periksa apakah 'composer_list' ada di data 'artist_role'
    if 'composer_list' in track_data['artist_role']:
         composer_list.extend(track_data['artist_role']['composer_list']['composer'])
    
    if composer_list:
         metadata['composer'] = ", ".join(composer_list)
    # --- BATAS TAMBAHAN BARU ---
    
    metadata['explicit'] = bool(track_data['song_is_explicit'])
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'track'
    
    # Sampul
    cover_template = track_data['album_photo_info']['url_template']
    metadata['cover'] = await _process_cover(metadata, cover_template)
    metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    # --- LOGIKA KUALITAS ---
    user_id = user.get('user_id')
    preferred_quality = kkbox_manager.get_user_quality(user_id)
    
    # Buat daftar prioritas berdasarkan preferensi pengguna
    user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    
    chosen_quality_key = None
    
    # Cek kualitas yang tersedia di lagu DAN di akun
    for q_key in user_quality_order:
        if q_key in track_data['audio_quality'] and q_key in client.available_qualities:
            chosen_quality_key = q_key
            break
            
    if not chosen_quality_key:
        # Fallback jika preferensi pengguna tidak tersedia
        for q_key in reversed(QUALITY_ORDER): # Coba dari yang terendah
             if q_key in track_data['audio_quality'] and q_key in client.available_qualities:
                chosen_quality_key = q_key
                break

    if not chosen_quality_key:
        raise KKBoxError(f"Tidak ada kualitas yang kompatibel ditemukan untuk track {track_id} (Akun: {client.available_qualities}, Track: {track_data['audio_quality']})")

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_quality_key]
    
    # Simpan info unduhan
    metadata['download_id'] = track_data['song_more_url'].split('/')[-1]
    metadata['download_quality_key'] = chosen_quality_key # misal: "hifi" atau "320k"
    
    return metadata

# --- FUNGSI BARU ---
async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album (diadaptasi dari interface.py)"""
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        # Panggil API di thread terpisah
        
        # --- PERBAIKAN SYNTAXERROR DI SINI ---
        album_resp = await asyncio.to_thread(client.get_album, album_id)
        # --- BATAS PERBAIKAN ---
        
        raw_id = album_resp['album']['album_id']
        
        album_data_more = await asyncio.to_thread(client.get_album_more, raw_id)
        alb_info = album_data_more['info']
        tracks_list = album_data_more['song_list']['song']
        alb_info['num_tracks'] = len(tracks_list)

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    metadata['itemid'] = album_id
    metadata['title'] = alb_info['album_name']
    metadata['album'] = alb_info['album_name']
    metadata['artist'] = alb_info['artist_name']
    metadata['albumartist'] = alb_info['artist_name']
    metadata['date'] = alb_info['album_date']
    metadata['totaltracks'] = str(alb_info['num_tracks'])
    
    # --- TAMBAHAN: Mengambil Total Volume (Disk) ---
    # Kita asumsikan API key-nya adalah 'num_volumes', default ke 1
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    # --- BATAS TAMBAHAN ---
    
    metadata['explicit'] = bool(alb_info['album_is_explicit'])
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'album'
    
    # Sampul
    cover_template = alb_info['album_photo_info']['url_template']
    metadata['cover'] = await _process_cover(metadata, cover_template)
    metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    metadata['tracks'] = []
    for song_data in tracks_list:
        try:
            track_id = song_data['song_more_url'].split('/')[-1]
            # Kirim pre_data dan alb_info_pre agar tidak perlu fetch ulang
            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=song_data, 
                alb_info_pre=alb_info
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal memproses track {song_data.get('song_more_url')} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
# --- BATAS FUNGSI BARU ---
