import os
import aiofiles
import hashlib
from Cryptodome.Cipher import AES # Wajib install pycryptodomex
from config import Config
from bot.logger import LOGGER
from ..message import edit_message
from .metadata import process_album_metadata
from ..utils import (
    format_string, run_concurrent_tasks, zip_handler, 
    fetch_zip_settings, post_art_poster, progress_message
)
from ..uploder import album_upload
from ..metadata import set_metadata
from pathvalidate import sanitize_filepath

# [span_14](start_span)Rahasia statis dari moov-dl.py[span_14](end_span)
SECRET_SALT = "F4:8E:09:CE:54:F7SeCrEtKkK"

async def start_moov(url: str, user: dict):
    # Parsing URL: https://moov.hk/#/album/ALBUM_ID
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
            raise Exception("Metadata album kosong.")
        
        album_meta = await process_album_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata Moov: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Moov/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        # Import helper untuk post cover
        from ..utils import post_art_poster
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(download_track(track, user, album_folder))

    update_details = {
        'text': "Downloading: {0} {1}/{2}\n{3} ({4})", # Template standar
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': 'album'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [t for t, success in zip(album_meta['tracks'], task_results) if success]
    album_meta['tracks'] = successful_tracks
    
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
    client = user['moov_api']
    
    # 1. Dapatkan info stream (m3u8 & Key)
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

    # 2. [span_15](start_span)Setup Decryption Key[span_15](end_span)
    try:
        m = hashlib.md5()
        m.update((content_key + SECRET_SALT).encode('UTF-8'))
        key = bytes.fromhex(m.hexdigest())
        iv = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01'
        cipher = AES.new(key, AES.MODE_CBC, iv)
    except Exception as e:
        LOGGER.error(f"Crypto setup failed: {e}")
        return False

    # 3. Download & Decrypt Segments
    # Moov menggunakan HLS. Kita perlu fetch m3u8, lalu download segmen, decrypt, dan gabung.
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    filepath = f"{folderpath}/{sanitize_filepath(raw_filename)}.flac"
    track_meta['filepath'] = filepath
    
    if not os.path.isdir(folderpath):
        os.makedirs(folderpath, exist_ok=True)

    try:
        # Fetch playlist m3u8
        # [span_16](start_span)Header user-agent khusus stream[span_16](end_span)
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        
        async with client.session.get(play_url, headers=hls_headers) as resp:
            m3u8_content = await resp.text()
            
        # Parse segments (baris yang tidak diawali #)
        segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        
        if not segments:
            return False

        # Download loop (Sequential writing to file)
        async with aiofiles.open(filepath, 'wb') as f_out:
            for seg_url in segments:
                for _ in range(3):
                    try:
                        # Proxy sudah dihandle oleh session connector
                        async with client.session.get(seg_url) as seg_resp: 
                            if seg_resp.status == 200:
                                encrypted_data = await seg_resp.read()
                                decrypted_data = cipher.decrypt(encrypted_data)
                                await f_out.write(decrypted_data)
                                break
                    except:
                        continue
                        
    except Exception as e:
        LOGGER.error(f"Download/Decrypt loop failed for {track_meta['title']}: {e}")
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

    # 4. [span_18](start_span)Lirik[span_18](end_span)
    try:
        lyrics = await client.get_lyrics(track_meta['itemid'])
        if lyrics:
            lrc_path = filepath.rsplit('.', 1)[0] + ".lrc"
            async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                await f.write(lyrics)
    except:
        pass

    # 5. Tagging
    try:
        await set_metadata(track_meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Tagging failed: {e}")
        return False
        
    return True
