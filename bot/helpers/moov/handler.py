# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
import traceback
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
    clean_url = url.replace("#/", "/") 
    
    if "/album/" in clean_url:
        raw_id = clean_url.split("/album/")[-1]
        album_id = raw_id.split("?")[0].split("/")[0]
        await start_album(album_id, user)
        
    elif "/song/" in clean_url:
        raw_id = clean_url.split("/song/")[-1]
        track_id = raw_id.split("?")[0].split("/")[0]
        await start_track_single(track_id, user)

    # Parsing Link Share
    elif "/share/" in clean_url and "/ADO/" in clean_url:
        try:
            parts = clean_url.split("/AUDIO/")
            left_part = parts[0].split("/ADO/")[-1]
            track_id = left_part.split("/")[0]
            right_part = parts[1]
            album_id = right_part.split("?")[0].split("/")[0]
            
            LOGGER.info(f"Share Link Parsed. Track: {track_id}, Album: {album_id}")
            await start_album(album_id, user, filter_track_id=track_id)
            
        except Exception as e:
            raise Exception(f"Gagal memparsing link Share Moov: {e}")
    else:
        raise Exception("Link Moov tidak dikenali. Saat ini hanya mendukung Album, Lagu, dan Share Link.")

async def start_track_single(track_id, user):
    client = user['moov_api']
    try:
        if not hasattr(client, 'get_product_meta'):
             raise Exception("Client Moov versi lama. Gunakan link Album/Share.")
        
        track_data = await client.get_product_meta(track_id)
        if not track_data: raise Exception("Data lagu tidak ditemukan.")

        album_id = track_data.get('albumId') or track_data.get('album', {}).get('id')
        if not album_id: raise Exception("Gagal menemukan ID Album.")

        LOGGER.info(f"Downloading Single Track: {track_id} from Album: {album_id}")
        await start_album(album_id, user, filter_track_id=track_id)

    except Exception as e:
        raise Exception(f"Gagal memproses lagu: {e}")

async def start_album(album_id, user, upload=True, filter_track_id=None):
    client = user['moov_api']
    try:
        raw_data = await client.get_album_meta(album_id)
        if not raw_data: raise Exception("Metadata album kosong.")
        album_meta = await process_album_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal metadata Moov: {e}")

    if filter_track_id:
        filtered_tracks = [
            t for t in album_meta['tracks'] 
            if str(t.get('itemid')) == str(filter_track_id)
        ]
        
        if not filtered_tracks:
            filtered_tracks = [
                t for t in album_meta['tracks'] 
                if str(filter_track_id) in str(t.get('itemid'))
            ]
        
        if not filtered_tracks:
            raise Exception(f"Lagu dengan ID {filter_track_id} tidak ditemukan.")
            
        album_meta['tracks'] = filtered_tracks
        album_meta['totaltracks'] = 1 
        album_meta['type'] = 'track'

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    
    album_meta['folderpath'] = album_folder

    if upload:
        try:
            from ..utils import post_art_poster
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
        except Exception as e:
            LOGGER.error(f"Poster Error (Ignored): {e}")

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(download_track(track, user, album_folder))

    dl_type = 'Single Track' if filter_track_id else 'Album'
    update_details = {
        'text': f"Downloading {dl_type}: {{0}} {{1}}/{{2}}\n{{3}} ({{4}})", 
        'msg': user['bot_msg'], 
        'title': album_meta['title'], 'type': 'album'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    album_meta['tracks'] = successful_tracks
    
    if successful_tracks:
        LOGGER.info(f"[HANDLER FINAL] Tracks Ready. Sample: {successful_tracks[0]['filepath']}")
        
        # --- FIX UPLOADER ---
        if filter_track_id and len(successful_tracks) == 1:
            track_data = successful_tracks[0]
            # Salin semua kunci penting ke Root Metadata
            album_meta['filepath'] = track_data['filepath']
            album_meta['file_path'] = track_data['filepath']
            album_meta['path'] = track_data['filepath']
            album_meta['file'] = track_data['filepath'] # Tambahan baru
            album_meta['duration'] = track_data.get('duration', 0)
    else:
        raise Exception("Gagal mengunduh lagu.")

    try:
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
        if album_zip and not filter_track_id: 
            await edit_message(user['bot_msg'], "Zipping...")
            album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
    except Exception as e:
        LOGGER.error(f"Zip Error: {e}")
        
    if upload:
        await edit_message(user['bot_msg'], "Uploading...")
        await album_upload(album_meta, user)

async def apply_mutagen_tags(filepath, meta, cover_path, lyrics=None):
    try:
        audio = FLAC(filepath)
        audio.delete() 
        
        audio['TITLE'] = meta.get('title', '')
        audio['ARTIST'] = meta.get('artist', '')
        audio['ALBUM'] = meta.get('album', '')
        audio['ALBUMARTIST'] = meta.get('albumartist', '')
        audio['GENRE'] = meta.get('genre', '')
        audio['COMPOSER'] = meta.get('composer', '')
        audio['COPYRIGHT'] = meta.get('copyright', '')
        audio['DISCNUMBER'] = str(meta.get('disk', ''))
        audio['TRACKNUMBER'] = str(meta.get('tracknumber', ''))
        
        if meta.get('totaltracks'):
            audio['TRACKTOTAL'] = str(meta.get('totaltracks'))
            audio['TOTALTRACKS'] = str(meta.get('totaltracks'))
        
        if meta.get('date'):
            audio['DATE'] = str(meta.get('date'))
            audio['ORIGINALDATE'] = str(meta.get('date'))

        if meta.get('label'):
            audio['ORGANIZATION'] = meta.get('label', '')
            audio['LABEL'] = meta.get('label', '')

        if lyrics and isinstance(lyrics, str) and len(lyrics) > 10:
            audio['LYRICS'] = lyrics
            audio['UNSYNCEDLYRICS'] = lyrics 
        
        if cover_path and os.path.exists(cover_path):
            p = Picture()
            with open(cover_path, 'rb') as f:
                p.data = f.read()
            p.type = 3 
            p.mime = 'image/jpeg'
            p.desc = 'Front Cover'
            audio.add_picture(p)
            
        audio.save()
        return int(audio.info.length)
        
    except Exception as e:
        LOGGER.error(f"Mutagen Error: {e}")
        return 0

async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    client = user['moov_api']
    
    try:
        try:
            file_meta = await client.get_track_file_meta(meta['itemid'], meta['moov_quality_code'])
            play_url = file_meta.get('playUrl')
            content_key = file_meta.get('contentKey')
            if not play_url or not content_key: return False
        except: return False

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
        
        # --- FIX: FULL KEYS FOR UPLOADER ---
        # Pastikan path absolut
        abs_path = os.path.abspath(final_filepath)
        meta['filepath'] = abs_path
        meta['file_path'] = abs_path
        meta['path'] = abs_path
        meta['file'] = abs_path # Tambahan kunci 'file'
        meta['filename'] = os.path.basename(abs_path)
        meta['is_downloaded'] = True
        meta['success'] = True
        # -----------------------------------
        
        key_filepath = os.path.join(track_temp_dir, "key.bin")
        async with aiofiles.open(key_filepath, 'wb') as f:
            await f.write(key_bytes)

        # COVER DOWNLOAD
        cover_local_path = None
        target_url = meta.get('cover_url')

        if target_url:
            cover_local_path = os.path.join(track_temp_dir, "cover.jpg")
            try:
                import aiohttp
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_url, headers=headers, timeout=30) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            async with aiofiles.open(cover_local_path, 'wb') as f:
                                await f.write(data)
                        else:
                            cover_local_path = None
            except:
                cover_local_path = None
        
        if not cover_local_path and meta.get('cover') and os.path.exists(meta.get('cover')):
            cover_local_path = os.path.join(track_temp_dir, "cover_fallback.jpg")
            shutil.copy(meta['cover'], cover_local_path)

        # SEGMENT DOWNLOAD
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

        # FFMPEG
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

        # LYRICS
        lyrics_text = None
        try:
            track_id = str(meta.get('itemid', ''))
            if track_id: lyrics_text = await client.get_lyrics(track_id)
        except: lyrics_text = None

        # TAGGING
        real_duration = await apply_mutagen_tags(final_filepath, meta, cover_local_path, lyrics=lyrics_text)
        if real_duration > 0: meta['duration'] = real_duration
            
        # COVER CLEANUP
        if cover_local_path and os.path.exists(cover_local_path):
            album_cover_path = os.path.join(folderpath, "cover.jpg")
            if not os.path.exists(album_cover_path):
                shutil.copy(cover_local_path, album_cover_path)
            meta['cover'] = album_cover_path
        else:
            meta['cover'] = None

        if lyrics_text and isinstance(lyrics_text, str):
            try:
                lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
                async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                    await f.write(lyrics_text)
            except: pass

        shutil.rmtree(track_temp_dir)

    except Exception as e:
        LOGGER.error(f"DL Crash: {e}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False
        
    return meta
