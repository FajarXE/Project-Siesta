# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import aiofiles
import hashlib
import traceback
from Cryptodome.Cipher import AES 
from config import Config
from bot.logger import LOGGER
from ..message import edit_message
from .metadata import process_album_metadata
from ..utils import (
    format_string, run_concurrent_tasks, zip_handler, 
    fetch_zip_settings, post_art_poster
)
from ..uploder import album_upload
from ..metadata import set_metadata

# Rahasia statis
SECRET_SALT = "F4:8E:09:CE:54:F7SeCrEtKkK"

# --- FUNGSI SANITASI MANUAL ---
def safe_name(name):
    """Membersihkan nama file dari karakter ilegal (Windows/Linux compatible)."""
    # Ganti karakter ilegal dengan underscore
    return re.sub(r'[\/:*?"><|]', '_', str(name)).strip()

async def start_moov(url: str, user: dict):
    if "/album/" not in url:
        await edit_message(user['bot_msg'], "Saat ini hanya mendukung link Album Moov.")
        return
    
    try:
        album_id = url.split("/album/")[-1].split("?")[0]
        await start_album(album_id, user)
    except Exception as e:
        LOGGER.error(f"Moov Error: {e}")
        await edit_message(user['bot_msg'], f"Error: {e}")

async def start_album(album_id, user, upload=True):
    client = user['moov_api']
    
    try:
        raw_data = await client.get_album_meta(album_id)
        if not raw_data:
            raise Exception("Metadata album kosong/tidak ditemukan.")
        
        album_meta = await process_album_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata Moov: {e}")

    # --- SETUP PATH ABSOLUT ---
    # Gunakan path absolut penuh agar tidak ada keraguan lokasi file
    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    
    # Sanitasi nama folder
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    
    # Rakit folder path
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    
    # Simpan ke metadata
    album_meta['folderpath'] = album_folder

    if upload:
        from ..utils import post_art_poster
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(download_track(track, user, album_folder))

    update_details = {
        'text': "Downloading: {0} {1}/{2}\n{3} ({4})", 
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': 'album'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [t for t, success in zip(album_meta['tracks'], task_results) if success]
    album_meta['tracks'] = successful_tracks
    
    if not successful_tracks:
        raise Exception("Gagal mengunduh semua lagu (File kosong atau gagal decrypt).")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if album_zip:
        await edit_message(user['bot_msg'], "Zipping...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        
    if upload:
        await edit_message(user['bot_msg'], "Uploading...")
        await album_upload(album_meta, user)

async def download_track(track_meta, user, folderpath):
    client = user['moov_api']
    
    # 1. Dapatkan info stream
    try:
        file_meta = await client.get_track_file_meta(track_meta['itemid'], track_meta['moov_quality_code'])
        play_url = file_meta.get('playUrl')
        content_key = file_meta.get('contentKey')
        
        if not play_url or not content_key:
            LOGGER.warning(f"Stream info missing for {track_meta['title']}")
            return False
            
    except Exception as e:
        LOGGER.error(f"Failed get stream {track_meta['title']}: {e}")
        return False

    # 2. Setup Key
    try:
        m = hashlib.md5()
        m.update((content_key + SECRET_SALT).encode('UTF-8'))
        key = bytes.fromhex(m.hexdigest())
        iv = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        cipher = AES.new(key, AES.MODE_CBC, iv)
    except Exception as e:
        LOGGER.error(f"Crypto setup failed: {e}")
        return False

    # 3. Pathing & Download
    # Format nama file dari config
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    # Sanitasi manual
    safe_filename = safe_name(raw_filename)
    
    # Path absolut file
    filepath = os.path.join(folderpath, f"{safe_filename}.flac")
    
    # PENTING: Update metadata di memori agar uploader membacanya
    track_meta['filepath'] = filepath
    
    if not os.path.isdir(folderpath):
        os.makedirs(folderpath, exist_ok=True)

    try:
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        
        async with client.session.get(play_url, headers=hls_headers) as resp:
            if resp.status != 200:
                LOGGER.error(f"M3U8 fetch failed: {resp.status}")
                return False
            m3u8_content = await resp.text()
            
        segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        
        if not segments:
            LOGGER.error(f"No segments found for {track_meta['title']}")
            return False

        async with aiofiles.open(filepath, 'wb') as f_out:
            for seg_url in segments:
                for _ in range(3):
                    try:
                        async with client.session.get(seg_url) as seg_resp:
                            if seg_resp.status == 200:
                                encrypted_data = await seg_resp.read()
                                decrypted_data = cipher.decrypt(encrypted_data)
                                await f_out.write(decrypted_data)
                                break
                    except:
                        continue
                        
    except Exception as e:
        LOGGER.error(f"Download loop failed for {track_meta['title']}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

    # 4. Validasi File Fisik
    if not os.path.exists(filepath):
        LOGGER.error(f"File NOT FOUND on disk after write: {filepath}")
        return False
        
    if os.path.getsize(filepath) == 0:
        LOGGER.error(f"File EMPTY (0 bytes): {filepath}")
        os.remove(filepath) # Hapus file kosong
        return False

    # 5. Lirik
    try:
        lyrics = await client.get_lyrics(track_meta['itemid'])
        if lyrics:
            lrc_path = filepath.rsplit('.', 1)[0] + ".lrc"
            async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                await f.write(lyrics)
    except:
        pass

    # 6. Tagging
    try:
        await set_metadata(track_meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Tagging failed for {filepath}: {e}")
        # Jangan return False, biarkan upload berjalan meskipun tagging gagal
        # (asalkan file audio ada dan bisa diputar)
        pass 
        
    return True
