# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
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
        if not raw_data: raise Exception("Metadata album kosong.")
        album_meta = await process_album_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal metadata Moov: {e}")

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
        'title': album_meta['title'], 'type': 'album'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    album_meta['tracks'] = successful_tracks
    
    if successful_tracks:
        LOGGER.info(f"[HANDLER FINAL] Tracks Ready. Sample: {successful_tracks[0]['filepath']}")
    else:
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
    
    try:
        file_meta = await client.get_track_file_meta(meta['itemid'], meta['moov_quality_code'])
        play_url = file_meta.get('playUrl')
        content_key = file_meta.get('contentKey')
        if not play_url or not content_key: return False
    except Exception as e:
        LOGGER.error(f"Failed stream {meta['title']}: {e}")
        return False

    try:
        m = hashlib.md5()
        m.update((content_key + SECRET_SALT).encode('UTF-8'))
        key_bytes = bytes.fromhex(m.hexdigest())
    except: return False

    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, meta, user)
    safe_filename = safe_name(raw_filename)
    
    track_temp_dir = os.path.join(folderpath, f"temp_{meta['itemid']}")
    if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
    os.makedirs(track_temp_dir, exist_ok=True)

    final_filepath = os.path.join(folderpath, f"{safe_filename}.flac")
    meta['filepath'] = final_filepath
    
    key_filepath = os.path.join(track_temp_dir, "key.bin")
    async with aiofiles.open(key_filepath, 'wb') as f:
        await f.write(key_bytes)

    # --- DOWNLOAD COVER UNTUK FFMPEG ---
    cover_path = None
    if meta.get('cover'):
        try:
            cover_path = os.path.join(track_temp_dir, "cover.jpg")
            # Cover URL sudah high-res dari metadata.py
            async with client.session.get(meta['cover']) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    async with aiofiles.open(cover_path, 'wb') as f:
                        await f.write(data)
                else:
                    cover_path = None
        except:
            cover_path = None
    # -----------------------------------

    try:
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        async with client.session.get(play_url, headers=hls_headers) as resp:
            if resp.status != 200: return False
            m3u8_content = await resp.text()

        target_duration = 10
        media_sequence = 0
        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-TARGETDURATION"):
                target_duration = line.split(":")[1].strip()
            if line.startswith("#EXT-X-MEDIA-SEQUENCE"):
                media_sequence = int(line.split(":")[1].strip())

        remote_segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        local_segment_names = []
        
        for index, seg_url in enumerate(remote_segments):
            seg_name = f"seg_{index:04d}.flac"
            seg_path = os.path.join(track_temp_dir, seg_name)
            local_segment_names.append(seg_name)
            
            success = False
            for _ in range(3):
                try:
                    async with client.session.get(seg_url) as seg_resp:
                        if seg_resp.status == 200:
                            data = await seg_resp.read()
                            async with aiofiles.open(seg_path, 'wb') as f:
                                await f.write(data)
                            success = True
                            break
                except: continue
            
            if not success:
                shutil.rmtree(track_temp_dir)
                return False

        local_m3u8_path = os.path.join(track_temp_dir, "local.m3u8")
        iv_line = ""
        iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', m3u8_content)
        if iv_match: iv_line = f",IV=0x{iv_match.group(1)}"
            
        async with aiofiles.open(local_m3u8_path, 'w') as f:
            await f.write("#EXTM3U\n")
            await f.write("#EXT-X-VERSION:3\n")
            await f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
            await f.write(f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}\n")
            await f.write(f'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"{iv_line}\n')
            for seg_name in local_segment_names:
                await f.write(f"#EXTINF:{target_duration},\n")
                await f.write(f"{seg_name}\n")
            await f.write("#EXT-X-ENDLIST\n")

        # --- FFMPEG COMMAND UTAMA (Tags Lengkap) ---
        cmd = [
            'ffmpeg', '-y',
            '-allowed_extensions', 'ALL',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-i', local_m3u8_path, # Input 0
        ]

        if cover_path and os.path.exists(cover_path):
            cmd.extend(['-i', cover_path]) # Input 1
            cmd.extend(['-map', '0:a', '-map', '1:0'])
            cmd.extend(['-disposition:v', 'attached_pic'])
            cmd.extend(['-metadata:s:v', 'title="Album cover"'])
            cmd.extend(['-metadata:s:v', 'comment="Cover (front)"'])
        else:
            cmd.extend(['-map', '0:a'])

        # Suntikan Metadata Lengkap
        cmd.extend([
            '-metadata', f'title={meta.get("title", "")}',
            '-metadata', f'artist={meta.get("artist", "")}',
            '-metadata', f'album={meta.get("album", "")}',
            '-metadata', f'album_artist={meta.get("albumartist", "")}',
            '-metadata', f'track={meta.get("tracknumber", "")}',
            '-metadata', f'copyright={meta.get("copyright", "")}',
            # --- TAGS BARU ---
            '-metadata', f'date={meta.get("year", "")}',      # Year
            '-metadata', f'genre={meta.get("genre", "")}',    # Genre
            '-metadata', f'disc={meta.get("disk", "")}',      # Disc No
            '-metadata', f'composer={meta.get("composer", "")}', # Composer
            # -----------------
            final_filepath
        ])
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        shutil.rmtree(track_temp_dir)
        
        if process.returncode != 0:
            LOGGER.error(f"FFmpeg HLS Error: {stderr.decode()}")
            return False

    except Exception as e:
        LOGGER.error(f"DL Logic Error: {e}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False

    if not os.path.exists(final_filepath) or os.path.getsize(final_filepath) < 1024 * 50: 
        return False

    try:
        lyrics = await client.get_lyrics(meta['itemid'])
        if lyrics:
            lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
            async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                await f.write(lyrics)
    except: pass
    
    try:
        await set_metadata(meta, user['user_id'])
    except: pass 
        
    return meta
