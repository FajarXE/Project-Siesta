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
    
    # Path Akhir (FLAC)
    final_filepath = os.path.join(folderpath, f"{safe_filename}.flac")
    # Path Sementara (TS Encrypted Container) - Kita gabung manual ke sini dulu
    temp_ts_path = os.path.join(folderpath, f"{safe_filename}_temp.ts")
    
    meta['filepath'] = final_filepath
    
    if not os.path.isdir(folderpath):
        os.makedirs(folderpath, exist_ok=True)

    # 4. Download Loop
    try:
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        async with client.session.get(play_url, headers=hls_headers) as resp:
            if resp.status != 200:
                return False
            m3u8_content = await resp.text()
            
        # Parse Sequence
        start_seq = 0 # DEFAULT 0 (Ini penting!)
        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                try:
                    start_seq = int(line.split(":")[1].strip())
                except:
                    pass
                break
                
        # Parse Explicit IV (Jaga-jaga)
        custom_iv = None
        iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', m3u8_content)
        if iv_match:
            custom_iv = bytes.fromhex(iv_match.group(1))

        segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        
        # Buka file temp .ts untuk ditulis (append mode)
        async with aiofiles.open(temp_ts_path, 'wb') as f_out:
            for index, seg_url in enumerate(segments):
                # Hitung IV untuk segmen ini
                if custom_iv:
                    iv = custom_iv
                else:
                    # Logic IV Standar HLS: Sequence Number sebagai Big Endian Bytes
                    current_seq = start_seq + index
                    iv = current_seq.to_bytes(16, byteorder='big')
                
                # Download Retries
                seg_success = False
                for _ in range(3):
                    try:
                        async with client.session.get(seg_url) as seg_resp:
                            if seg_resp.status == 200:
                                encrypted_data = await seg_resp.read()
                                
                                # Reset Cipher Setiap Segmen!
                                cipher = AES.new(key, AES.MODE_CBC, iv)
                                decrypted_data = cipher.decrypt(encrypted_data)
                                
                                await f_out.write(decrypted_data)
                                seg_success = True
                                break
                    except:
                        continue
                
                if not seg_success:
                    LOGGER.error(f"Gagal download segmen {index} - {meta['title']}")
                    # Jangan return False, coba lanjut siapa tau segmen lain bisa (best effort)
                    # Atau return False jika ingin strict.

        # 5. Convert TS -> FLAC dengan FFmpeg
        # Ini akan memperbaiki header dan container
        if os.path.exists(temp_ts_path) and os.path.getsize(temp_ts_path) > 0:
            cmd = [
                'ffmpeg', '-y',
                '-i', temp_ts_path,
                '-c', 'copy', # Copy stream tanpa re-encode (Cepat)
                final_filepath
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            
            # Hapus file temp
            os.remove(temp_ts_path)
            
            if process.returncode != 0:
                LOGGER.error(f"FFmpeg Error: {stderr.decode()}")
                return False
        else:
            return False

    except Exception as e:
        LOGGER.error(f"DL Logic Error {meta['title']}: {e}")
        if os.path.exists(temp_ts_path):
            os.remove(temp_ts_path)
        return False

    # 6. Validasi Akhir
    if not os.path.exists(final_filepath) or os.path.getsize(final_filepath) < 1024 * 50: 
        LOGGER.error(f"File final too small/missing: {final_filepath}")
        return False

    # 7. Lyrics & Tagging
    try:
        lyrics = await client.get_lyrics(meta['itemid'])
        if lyrics:
            lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
            async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                await f.write(lyrics)
    except:
        pass

    try:
        await set_metadata(meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Tagging Error: {e}")
        pass 
        
    return meta
