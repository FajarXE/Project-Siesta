# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
from mutagen.flac import FLAC, Picture
from config import Config
from bot.logger import LOGGER
from ..message import edit_message
from .metadata import process_album_metadata
from ..utils import (
    format_string, run_concurrent_tasks, zip_handler, 
    fetch_zip_settings, post_art_poster
)
from ..uploder import album_upload

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

async def apply_mutagen_tags(filepath, meta, cover_path):
    try:
        audio = FLAC(filepath)
        audio.delete() # Bersihkan tag lama
        
        # Write Tags
        audio['TITLE'] = meta.get('title', '')
        audio['ARTIST'] = meta.get('artist', '')
        audio['ALBUM'] = meta.get('album', '')
        audio['ALBUMARTIST'] = meta.get('albumartist', '')
        audio['TRACKNUMBER'] = str(meta.get('tracknumber', ''))
        audio['DISCNUMBER'] = str(meta.get('disk', ''))
        audio['GENRE'] = meta.get('genre', '')
        audio['DATE'] = str(meta.get('year', ''))
        audio['COMPOSER'] = meta.get('composer', '')
        audio['COPYRIGHT'] = meta.get('copyright', '')
        
        # Embed Cover
        if cover_path and os.path.exists(cover_path):
            p = Picture()
            with open(cover_path, 'rb') as f:
                p.data = f.read()
            p.type = 3 
            p.mime = 'image/jpeg'
            p.desc = 'Front Cover'
            audio.add_picture(p)
        else:
            LOGGER.warning(f"[TAG] No cover found for {meta['title']}")
            
        audio.save()
        return int(audio.info.length)
        
    except Exception as e:
        LOGGER.error(f"Mutagen Error: {e}")
        return 0

async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    client = user['moov_api']
    
    try:
        file_meta = await client.get_track_file_meta(meta['itemid'], meta['moov_quality_code'])
        play_url = file_meta.get('playUrl')
        content_key = file_meta.get('contentKey')
        if not play_url or not content_key: return False
    except Exception as e:
        LOGGER.error(f"Stream Error: {e}")
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

    # --- DOWNLOAD COVER (Priority: Metadata URL > Local File) ---
    cover_local_path = None
    target_url = meta.get('cover_url') # Ini sekarang mungkin URL iTunes High Res

    if target_url:
        cover_local_path = os.path.join(track_temp_dir, "cover.jpg")
        try:
            # Gunakan session khusus untuk download cover external (iTunes/CDN)
            # agar tidak crash dengan session Moov API
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(target_url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        async with aiofiles.open(cover_local_path, 'wb') as f:
                            await f.write(data)
                    else:
                        LOGGER.warning(f"Failed to download cover from {target_url}: {resp.status}")
                        cover_local_path = None
        except Exception as e:
            LOGGER.error(f"Cover Download Error: {e}")
            cover_local_path = None
    
    # Fallback: Jika download gagal, cek apakah sudah ada cover lokal dari proses album
    if not cover_local_path and meta.get('cover') and os.path.exists(meta.get('cover')):
         cover_local_path = os.path.join(track_temp_dir, "cover_fallback.jpg")
         shutil.copy(meta['cover'], cover_local_path)
    # -----------------------------------------------------------

    # DOWNLOAD SEGMENTS
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

        # FFMPEG STITCHING
        cmd = [
            'ffmpeg', '-y',
            '-allowed_extensions', 'ALL',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-i', local_m3u8_path,
            '-c', 'flac', 
            final_filepath
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode != 0:
            LOGGER.error(f"FFmpeg Error: {stderr.decode()}")
            shutil.rmtree(track_temp_dir)
            return False

        if not os.path.exists(final_filepath): return False

        # TAGGING MUTAGEN
        real_duration = await apply_mutagen_tags(final_filepath, meta, cover_local_path)
        
        if real_duration > 0:
            meta['duration'] = real_duration
            
        if cover_local_path and os.path.exists(cover_local_path):
            final_cover_path = os.path.join(folderpath, f"cover_{meta['itemid']}.jpg")
            shutil.move(cover_local_path, final_cover_path)
            meta['cover'] = final_cover_path
        else:
            meta['cover'] = None 

        try:
            lyrics = await client.get_lyrics(meta['itemid'])
            if lyrics:
                lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
                async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                    await f.write(lyrics)
        except: pass

        shutil.rmtree(track_temp_dir)

    except Exception as e:
        LOGGER.error(f"DL Logic Error: {e}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False
        
    return meta
