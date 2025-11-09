# [GANTI FILE: bot/helpers/idagio/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio
import requests # Diperlukan untuk unduhan sinkron

from pathvalidate import sanitize_filepath
from config import Config
from Cryptodome.Cipher import AES
from Cryptodome.Hash import SHA256

from .metadata import (
    process_track_metadata, 
    process_album_metadata,
    custom_url_parse
)
from .manager import IdagioError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

async def start_idagio(url: str, user: dict):
    """Handler utama untuk link Idagio."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        elif media_type == 'album':
            await start_album(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media Idagio '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Idagio handler: {e}\n{traceback.format_exc()}")
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    client = user['idagio_api']

    if not track_meta:
        try:
            # item_id di sini adalah 'recording_id'
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            # --- PERBAIKAN: Tambahkan logging traceback lengkap ---
            LOGGER.error(f"Idagio track {item_id} gagal di process_track_metadata: {e}\n{traceback.format_exc()}")
            # --- BATAS PERBAIKAN ---
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    quality_tier = track_meta.get('download_quality_tier') # 90, 70, 50
    stream_track_id = track_meta.get('download_track_id') # ID untuk stream
    
    if not quality_tier or not stream_track_id:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan Idagio track {item_id} (Tier: {quality_tier}, StreamID: {stream_track_id})")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    # --- Potong nama file (safe_filename) agar tidak terlalu panjang ---
    max_len = 150
    if len(safe_filename) > max_len:
        safe_filename = safe_filename[:max_len].strip() # Potong dan hapus spasi
        LOGGER.warning(f"Idagio: Nama file dipotong menjadi: {safe_filename}")
    # --- BATAS PERBAIKAN ---

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- LOGIKA UNDUH IDAGIO (Dekripsi) ---
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Jalankan unduhan + dekripsi sinkron di thread terpisah
        await asyncio.to_thread(
            download_track_encrypted,
            client, # Objek IdagioApi (dengan sesi requests)
            stream_track_id,
            quality_tier,
            track_meta['filepath']
        )

    except Exception as e:
        # --- PERBAIKAN: Tambahkan logging traceback lengkap ---
        LOGGER.error(f"Idagio dl_track gagal untuk {item_id}: {e}\n{traceback.format_exc()}")
        # --- BATAS PERBAIKAN ---
        return False
    # --- BATAS LOGIKA UNDUH ---

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Idagio: {filepath}")
        return False
    except Exception as e:
        # --- PERBAIKAN: Tambahkan logging traceback lengkap ---
        LOGGER.error(f"Gagal memproses metadata Idagio: {filepath} -> {e}\n{traceback.format_exc()}")
        # --- BATAS PERBAIKAN ---
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


def download_track_encrypted(client, track_id, quality_tier, temp_location):
    """
    Fungsi SINKRON untuk mengunduh dan mendekripsi file Idagio.
    Dijalankan di ThreadPoolExecutor oleh asyncio.to_thread.
    Logika diadaptasi dari interface.py
    """
    
    # 1. Dapatkan stream data (ini menggunakan 'requests' dari 'client.s')
    stream_data_list = client.get_track_stream(track_id, quality=quality_tier)
    
    if not stream_data_list:
        # Coba fallback ke endpoint Sonos (hanya FLAC)
        if quality_tier == 90:
            LOGGER.debug(f"Idagio: Gagal mendapatkan stream, mencoba fallback Sonos...")
            stream_data_list = client.get_track_stream_2(track_id, quality=quality_tier)
        if not stream_data_list:
            raise IdagioError(f"Tidak bisa mendapatkan data stream untuk track {track_id}")

    stream_data = stream_data_list[0]
    
    # 2. Mulai streaming unduhan
    r = client.s.get(stream_data.get('url'), stream=True)
    r.raise_for_status()

    # 3. Cek enkripsi dan siapkan cipher
    is_encrypted = False
    cipher = None
    
    if r.headers.get('X-X'):
        is_encrypted = True
        base_key, iv = r.headers['X-X'].split(' ')

        secret = 'mola*jbaf^*`*V^fG^lkf4fb_bba2'
        offset = 3
        extended_key = ''.join(map(chr, [(ord(char) + offset + 65536) % 65536 for char in secret]))

        key = base_key + extended_key
        key_checksum = SHA256.new(key.encode('utf-8')).hexdigest()[:16].encode('utf-8')
        iv = iv.encode('utf-8')

        cipher = AES.new(key_checksum, AES.MODE_CTR, initial_value=iv, nonce=b'')
        LOGGER.debug(f"Idagio: Mendeteksi stream terenkripsi. Menggunakan AES-CTR.")
    else:
        LOGGER.debug(f"Idagio: Mendeteksi stream tidak terenkripsi.")

    # 4. Unduh, Dekripsi (jika perlu), dan Tulis
    try:
        with open(temp_location, 'wb') as f:
            if is_encrypted:
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        f.write(cipher.decrypt(chunk))
            else:
                # Tidak terenkripsi (misal fallback Sonos)
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        # Hapus file parsial jika gagal
        if os.path.isfile(temp_location):
            os.remove(temp_location)
        raise e
    
    LOGGER.info(f"Idagio: Berhasil mengunduh dan mendekripsi ke {temp_location}")


async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album.
    """
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Idagio: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # --- Implementasi Semaphore manual ---
    
    # 1. Tentukan batas unduhan bersamaan (concurrent)
    # --- PERBAIKAN: Turunkan limit ke 1 untuk diagnosis ---
    sem = asyncio.Semaphore(1) # Batas 1 unduhan simultan
    # --- BATAS PERBAIKAN ---
    total_tracks = len(album_meta['tracks'])
    completed_count = 0
    
    # 2. Buat fungsi wrapper untuk menjalankan tugas dengan batasan semaphore
    async def run_task_with_limit(task_coro, track_meta):
        nonlocal completed_count
        async with sem:
            # 'task_coro' adalah 'start_track(...)'
            result = await task_coro
            
            # Update progres
            completed_count += 1
            # --- PERBAIKAN: Update setiap 1 lagu karena limit=1 ---
            if completed_count % 1 == 0 or completed_count == total_tracks: # Update setiap 1 lagu
            # --- BATAS PERBAIKAN ---
                try:
                    await edit_message(
                        user['bot_msg'],
                        lang.s.DOWNLOAD_PROGRESS.format(
                            completed_count,
                            total_tracks,
                            album_meta['title'],
                            f"{int((completed_count/total_tracks)*100)}%"
                        )
                    )
                except:
                    pass # Jangan gagalkan semua jika edit pesan gagal
            
            return result, track_meta # Kembalikan hasil dan meta

    # 3. Siapkan semua tugas (coroutines)
    task_coroutines = []
    for track in album_meta['tracks']:
        # 'itemid' di sini adalah recording_id
        task_coro = start_track(track['itemid'], user, track, False, album_folder)
        task_coroutines.append(run_task_with_limit(task_coro, track))

    # 4. Jalankan semua tugas (dibatasi oleh semaphore)
    task_results_with_meta = await asyncio.gather(*task_coroutines)
    
    # --- BATAS PERBAIKAN ---

    # 5. Filter hasil
    successful_tracks = []
    for result, track_meta in task_results_with_meta:
        if result: # 'result' adalah boolean True/False dari start_track
            successful_tracks.append(track_meta)
            
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Idagio yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
