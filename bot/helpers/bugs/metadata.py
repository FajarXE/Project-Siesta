# [GANTI FILE: bot/helpers/bugs/metadata.py]

import copy
import re
import asyncio
import logging
from datetime import datetime
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import bugs_manager, BugsError
from bot.logger import LOGGER

# --- PERBAIKAN: Hapus 'flac24' ---
QUALITY_MAP_DISPLAY = {
    'flac': ("FLAC 16-bit", "flac"),
    'aac256': ("AAC 256k", "m4a"),
    '320k': ("MP3 320k", "mp3"),
    'aac': ("AAC 128k", "m4a")
}
# Urutan prioritas kualitas dari interface.py
QUALITY_ORDER = ["flac", "aac256", "320k", "aac"]
# --- BATAS PERBAIKAN ---

# Ukuran gambar yang didukung oleh API Bugs (dari interface.py)
BUGS_SUPPORTED_COVER_SIZES = [75, 140, 200, 350, 500, 1000, 1280, 1400, 2000, 3001]

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Bugs"""
    url = urlparse(link)
    path_match = None
    
    # --- PERBAIKAN: Tambahkan 'm.bugs.co.kr' sebagai hostname yang valid ---
    if url.hostname in ('music.bugs.co.kr', 'm.bugs.co.kr'):
        # Pola untuk track, album, dan artist
        path_match = re.match(r'^\/(track|album|artist)\/(\d+)', url.path)
    # --- BATAS PERBAIKAN ---
    else:
        raise BugsError(f'URL tidak valid: {link}')
        
    if not path_match:
        raise BugsError(f'URL tidak valid atau tidak didukung: {link}')
    
    type = path_match.group(1)
    
    return type, path_match.group(2), {}

async def _process_cover(metadata: dict, cover_path: str, base_size: int = 1400):
    """
    Memproses sampul dari path gambar Bugs.
    Logika ini diadaptasi dari _generate_artwork_url di interface.py
    """
    if not cover_path:
        return None

    # Cari ukuran terdekat yang didukung
    best_size = min(BUGS_SUPPORTED_COVER_SIZES, key=lambda x: abs(x - base_size))
    
    # 3001 berarti 'original'
    cover_size_str = str(best_size) if best_size <= 3000 else 'original'
    
    # Buat URL lengkap
    url = f'https://image.bugsm.co.kr/album/images/{cover_size_str}{cover_path}'
    
    return await create_cover_file(url, metadata)

async def _process_thumbnail(metadata: dict, cover_path: str):
    """Membuat thumbnail (menggunakan ukuran 200px)"""
    if not cover_path:
        return None
    
    # '200' adalah salah satu ukuran yang didukung
    url = f'https://image.bugsm.co.kr/album/images/200{cover_path}'
    
    return await create_cover_file(url, metadata, True)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    """
    Memproses metadata untuk satu lagu Bugs.
    Logika ini diadaptasi dari get_track_info di interface.py
    """
    client = user['bugs_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        # Panggil API di thread terpisah
        if pre_data:
            track_data = pre_data
        else:
            # [0].get('track').get('result')
            track_data_list = await asyncio.to_thread(client.get_track, track_id)
            track_data = track_data_list[0].get('track').get('result')
            
        # Dapatkan info album
        album_id = track_data.get('album', {}).get('album_id')
        if not album_id:
            raise BugsError(f"Gagal mendapatkan album_id dari track {track_id}")

        if alb_info_pre:
            album_data = alb_info_pre
        else:
            # [0].get('album').get('result')
            album_data_list = await asyncio.to_thread(client.get_album, album_id)
            album_data = album_data_list[0].get('album').get('result')

    except Exception as e:
        LOGGER.error(f"Bugs: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    # --- Pemetaan Tag (dari get_track_info) ---
    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('track_title')
    metadata['album'] = album_data.get('title')
    
    metadata['artist'] = ", ".join([a.get('artist_nm') for a in track_data.get('artists')])
    metadata['albumartist'] = album_data.get('artists')[0].get('artist_nm')
    
    metadata['tracknumber'] = str(track_data.get('track_no'))
    metadata['totaltracks'] = str(album_data.get('track_count'))
    metadata['discnumber'] = str(track_data.get('disc_no'))
    
    # --- PERBAIKAN: Gunakan default '1' jika 'disc_count' tidak ada ---
    metadata['totalvolume'] = str(album_data.get('disc_count') or 1)
    # --- BATAS PERBAIKAN ---
    
    # Format tanggal YYYYMMDD atau YYYYMM -> YYYY-MM-DD
    release_date_str = album_data.get('release_ymd')
    if release_date_str:
        try:
            if len(release_date_str) == 6: # YYYYMM
                release_date_str += '01' # Tambah hari default
            release_date_obj = datetime.strptime(release_date_str, '%Y%m%d')
            metadata['date'] = release_date_obj.strftime('%Y-%m-%d')
            metadata['year'] = release_date_obj.strftime('%Y')
        except ValueError:
            LOGGER.warning(f"Bugs: Gagal mem-parsing tanggal rilis: {release_date_str}")
            metadata['date'] = None
            metadata['year'] = None

    if album_data.get('genres'):
        metadata['genre'] = ", ".join([g.get('svc_nm') for g in album_data.get('genres')])
    
    if album_data.get("labels"):
        metadata['copyright'] = f'© {metadata["year"]} {album_data.get("labels")[0].get("label_nm")}'
    
    metadata['provider'] = 'Bugs'
    metadata['type'] = 'track'

    # --- PERBAIKAN: Atur 'explicit' ke False (default) ---
    # API Bugs yang disediakan tampaknya tidak memiliki flag 'adult_yn'
    metadata['explicit'] = False
    # --- BATAS PERBAIKAN ---
    
    # --- Sampul ---
    cover_path = album_data.get('image', {}).get('path')
    if cover_path:
        metadata['cover'] = await _process_cover(metadata, cover_path)
        metadata['thumbnail'] = await _process_thumbnail(metadata, cover_path)

    # --- Logika Kualitas (dari get_track_info) ---
    user_id = user.get('user_id')
    preferred_quality = bugs_manager.get_user_quality(user_id)
    
    # Buat daftar prioritas berdasarkan preferensi pengguna
    try:
        user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    except ValueError:
        user_quality_order = QUALITY_ORDER # Fallback ke default penuh

    chosen_quality_key = None
    
    track_bitrates = track_data.get('bitrates', []) # Kualitas yang tersedia di lagu
    
    # Cek apakah FLAC butuh premium
    rights = track_data.get('rights', {}).get('streaming', {})
    needs_premium_flac = rights.get('flac_premium_yn', False)
    
    # Cek status akun dari objek klien (diset saat login oleh manager.py)
    account_has_premium = getattr(client, 'account_flac_premium', False)

    # Cek ketersediaan
    if not rights.get('service_yn'):
        raise BugsError(f"Track '{metadata['title']}' tidak tersedia untuk streaming.")
    
    # 1. Coba cari dari preferensi pengguna ke bawah
    for q_key in user_quality_order:
        if q_key in track_bitrates:
            # Cek kasus khusus FLAC
            if 'flac' in q_key and needs_premium_flac and not account_has_premium:
                LOGGER.warning(f"Bugs: {q_key} tersedia, tetapi akun tidak memiliki Premium FLAC. Mencari kualitas lain...")
                continue # Lewati kualitas ini
            
            chosen_quality_key = q_key
            break
            
    # 2. Fallback: Jika preferensi pengguna tidak ditemukan (misal: ingin flac tapi tidak ada)
    if not chosen_quality_key:
        fallback_order = reversed(QUALITY_ORDER) # Coba dari yang terendah ke atas
        for q_key in fallback_order:
            if q_key in track_bitrates:
                if 'flac' in q_key and needs_premium_flac and not account_has_premium:
                    continue # Tetap lewati FLAC non-premium
                
                chosen_quality_key = q_key
                break # Ambil yang terendah yang tersedia

    if not chosen_quality_key:
        raise BugsError(f"Tidak ada kualitas yang kompatibel ditemukan untuk track {track_id} (Akun Premium FLAC: {account_has_premium}, Lagu Butuh Premium: {needs_premium_flac}, Kualitas Lagu: {track_bitrates})")

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_quality_key]
    
    # Simpan info unduhan
    metadata['download_id'] = track_id # Bugs men-download pakai track_id
    metadata['download_quality_key'] = chosen_quality_key # misal: "flac" atau "320k"
    
    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """
    Memproses metadata untuk satu album Bugs.
    Logika ini diadaptasi dari get_album_info di interface.py
    """
    client = user['bugs_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        # Panggil API di thread terpisah
        album_data_list = await asyncio.to_thread(client.get_album, album_id)
        album_data = album_data_list[0].get('album').get('result')
        
        tracks_list_data = await asyncio.to_thread(client.get_album_tracks, album_id)
        tracks_list = tracks_list_data[0].get('album_track').get('list')
        
    except Exception as e:
        LOGGER.error(f"Bugs: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    # --- Pemetaan Tag Album ---
    metadata['itemid'] = album_id
    metadata['title'] = album_data.get('title')
    metadata['album'] = album_data.get('title')
    metadata['artist'] = album_data.get('artists')[0].get('artist_nm')
    metadata['albumartist'] = album_data.get('artists')[0].get('artist_nm')
    
    release_date_str = album_data.get('release_ymd')
    if release_date_str:
        metadata['date'] = datetime.strptime(release_date_str, '%Y%m%d').strftime('%Y-%m-%d')
    
    metadata['totaltracks'] = str(album_data.get('track_count'))
    
    # --- PERBAIKAN: Gunakan default '1' jika 'disc_count' tidak ada ---
    metadata['totalvolume'] = str(album_data.get('disc_count') or 1)
    # --- BATAS PERBAIKAN ---
    
    metadata['provider'] = 'Bugs'
    metadata['type'] = 'album'
    
    # --- PERBAIKAN: Atur 'explicit' ke False (default) ---
    metadata['explicit'] = False
    # --- BATAS PERBAIKAN ---

    # --- Sampul ---
    cover_path = album_data.get('image', {}).get('path')
    if cover_path:
        metadata['cover'] = await _process_cover(metadata, cover_path)
        metadata['thumbnail'] = await _process_thumbnail(metadata, cover_path)

    metadata['tracks'] = []
    for song_data in tracks_list:
        try:
            track_id = song_data.get('track_id')
            # Kirim pre_data dan alb_info_pre agar tidak perlu fetch ulang
            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=song_data, 
                alb_info_pre=album_data
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"Bugs: Gagal memproses track {song_data.get('track_id')} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    # Gunakan kualitas dari lagu pertama sebagai tampilan
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
