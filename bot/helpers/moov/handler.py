# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
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

def safe_name(name):
    """Membersihkan nama file dari karakter ilegal."""
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

    # SETUP PATH
    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    
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
    
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    album_meta['tracks'] = successful_tracks
    
    if successful_tracks:
        LOGGER.info(f"[HANDLER FINAL] Tracks Ready. Sample: {successful_tracks[0]['filepath']}")

    if not successful_tracks:
        raise Exception("Gagal mengunduh semua lagu.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if album_zip:
        await edit_message(user['bot_msg'], "Zipping...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        
    if upload:
        await edit_message(user['bot_msg'], "Uploading...")
        await album_upload(album_meta, user)

async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    client = user['moov_api']
    
    # 1. Stream Info
    try:
        file_meta = await client.get_track_file_meta(meta['itemid'], meta['moov_quality_code'])
        play_url = file_meta.get('playUrl')
        content_key = file_meta.get('contentKey')
        if not play_url or not content_key:
            return False
    except Exception as e:
        LOGGER.error(f"Failed stream {meta['title']}: {e}")
        return False

    # 2. Key Derivation
    try:
        m = hashlib.md5()
        m.update((content_key + SECRET_SALT).encode('UTF-8'))
        key = bytes.fromhex(m.hexdigest())
    except:
        return False

    # 3. Pathing
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, meta, user)
    safe_filename = safe_name(raw_filename)
    filepath = os.path.join(folderpath, f"{safe_filename}.flac")
    
    meta['filepath'] = filepath
    
    # Folder temporary untuk menyimpan segmen pecahan
    temp_seg_dir = os.path.join(folderpath, f"temp_{meta['itemid']}")
    if os.path.exists(temp_seg_dir):
        shutil.rmtree(temp_seg_dir)
    os.makedirs(temp_seg_dir, exist_ok=True)

    if not os.path.isdir(folderpath):
        os.makedirs(folderpath, exist_ok=True)

    # 4. Download & Decrypt Loop
    try:
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        async with client.session.get(play_url, headers=hls_headers) as resp:
            if resp.status != 200:
                return False
            m3u8_content = await resp.text()
            
        # DEBUG: Log Key line untuk memastikan IV
        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-KEY"):
                LOGGER.info(f"[DEBUG M3U8] {meta['title']} Key Line: {line}")

        # Cari Sequence Awal
        start_seq = 1
        custom_iv = None
        
        # Cek apakah ada IV eksplisit di M3U8
        # Contoh: #EXT-X-KEY:METHOD=AES-128,URI="...",IV=0x123...
        key_match = re.search(r'IV=0x([0-9a-fA-F]+)', m3u8_content)
        if key_match:
            iv_hex = key_match.group(1)
            custom_iv = bytes.fromhex(iv_hex)
            LOGGER.info(f"[DEBUG IV] Found Explicit IV in M3U8: {iv_hex}")

        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                try:
                    start_seq = int(line.split(":")[1].strip())
                except:
                    pass
                break

        segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        segment_files = []

        for index, seg_url in enumerate(segments):
            seg_filename = os.path.join(temp_seg_dir, f"{index:04d}.ts")
            success = False
            
            for _ in range(3): # Retry logic
                try:
                    async with client.session.get(seg_url) as seg_resp:
                        if seg_resp.status == 200:
                            encrypted_data = await seg_resp.read()
                            
                            # LOGIKA IV:
                            # 1. Jika ada IV di M3U8, gunakan itu (Static).
                            # 2. Jika tidak, gunakan Sequence Number (Dynamic per segmen).
                            if custom_iv:
                                iv = custom_iv
                            else:
                                current_seq = start_seq + index
                                iv = current_seq.to_bytes(16, byteorder='big')
                            
                            # Reset Cipher untuk setiap segmen (Standard HLS untuk file pecahan)
                            cipher = AES.new(key, AES.MODE_CBC, iv)
                            decrypted_data = cipher.decrypt(encrypted_data)
                            
                            async with aiofiles.open(seg_filename, 'wb') as f_seg:
                                await f_seg.write(decrypted_data)
                            
                            segment_files.append(seg_filename)
                            success = True
                            break
                except Exception as e:
                    # LOGGER.error(f"Seg dl error: {e}")
                    pass
            
            if not success:
                LOGGER.error(f"Failed to download segment {index} for {meta['title']}")
                # Clean up and fail
                shutil.rmtree(temp_seg_dir)
                return False

        # 5. FFmpeg Concatenation (Stitching)
        # Ini akan menggabungkan semua segmen menjadi satu file FLAC utuh
        list_txt_path = os.path.join(temp_seg_dir, "list.txt")
        async with aiofiles.open(list_txt_path, 'w') as f_list:
            for seg_file in segment_files:
                # Escape single quotes in filename just in case
                safe_seg = seg_file.replace("'", "'\\''")
                await f_list.write(f"file '{safe_seg}'\n")

        # Command FFmpeg
        # -f concat: format gabung
        # -safe 0: izinkan path absolut
        # -c copy: jangan transcode (hanya copy stream audio), sangat cepat
        cmd = [
            'ffmpeg', '-y', 
            '-f', 'concat', 
            '-safe', '0', 
            '-i', list_txt_path, 
            '-c', 'copy', 
            filepath
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            LOGGER.error(f"FFmpeg Error for {meta['title']}: {stderr.decode()}")
            shutil.rmtree(temp_seg_dir)
            return False
            
        # Hapus folder temporary
        shutil.rmtree(temp_seg_dir)

    except Exception as e:
        LOGGER.error(f"DL Logic Error {meta['title']}: {e}")
        if os.path.exists(temp_seg_dir):
            shutil.rmtree(temp_seg_dir)
        return False

    # 6. Validasi Akhir
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 1024 * 100: 
        LOGGER.error(f"File final too small/missing: {filepath}")
        return False

    # 7. Lyrics & Tagging
    try:
        lyrics = await client.get_lyrics(meta['itemid'])
        if lyrics:
            lrc_path = filepath.rsplit('.', 1)[0] + ".lrc"
            async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                await f.write(lyrics)
    except:
        pass

    try:
        await set_metadata(meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Tagging Error {filepath}: {e}")
        pass 
        
    return meta
