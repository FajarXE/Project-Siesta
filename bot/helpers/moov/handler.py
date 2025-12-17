# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
import traceback
import urllib.parse
import aiohttp
from yarl import URL
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

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://moov.hk/',
    'Origin': 'https://moov.hk'
}

def safe_name(name):
    return re.sub(r'[\/:*?"><|#]', '_', str(name)).strip()

def resolve_url(base_url, relative_url):
    if relative_url.startswith('http'):
        return relative_url
    base_clean = base_url.split('?')[0]
    if not base_clean.endswith('/') and not os.path.splitext(base_clean)[1]:
        base_clean += '/'
    elif os.path.splitext(base_clean)[1]:
        base_clean = os.path.dirname(base_clean) + '/'
    return urllib.parse.urljoin(base_clean, relative_url)

def merge_urls(base_url, relative_url):
    base_parsed = urllib.parse.urlparse(base_url)
    base_params = dict(urllib.parse.parse_qsl(base_parsed.query))
    
    full_url = resolve_url(base_url, relative_url)
    final_parsed = urllib.parse.urlparse(full_url)
    final_params = dict(urllib.parse.parse_qsl(final_parsed.query))
    
    merged_params = base_params.copy()
    merged_params.update(final_params)
    
    new_query = urllib.parse.urlencode(merged_params)
    return final_parsed._replace(query=new_query).geturl()

async def download_resource(session, url, path):
    try:
        async with session.get(url, headers=BROWSER_HEADERS, timeout=20) as resp:
            if resp.status == 200:
                data = await resp.read()
                if len(data) > 0:
                    async with aiofiles.open(path, 'wb') as f: await f.write(data)
                    return True
            LOGGER.warning(f"Resource DL Failed ({resp.status}): {url}")
    except Exception as e:
        LOGGER.error(f"Resource DL Error ({url}): {e}")
    return False

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
        raise Exception("Link Moov tidak dikenali.")

async def start_track_single(track_id, user):
    client = user['moov_api']
    try:
        if not hasattr(client, 'get_product_meta'):
             raise Exception("Client Moov versi lama.")
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
        filtered_tracks = [t for t in album_meta['tracks'] if str(t.get('itemid')) == str(filter_track_id)]
        if not filtered_tracks:
            filtered_tracks = [t for t in album_meta['tracks'] if str(filter_track_id) in str(t.get('itemid'))]
        if not filtered_tracks:
            raise Exception(f"Lagu dengan ID {filter_track_id} tidak ditemukan.")
        album_meta['tracks'] = filtered_tracks

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    album_meta['folderpath'] = album_folder

    if upload and not filter_track_id:
        try:
            from ..utils import post_art_poster
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
        except Exception as e:
            LOGGER.error(f"Poster Error (Ignored): {e}")

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(download_track(track, user, album_folder))

    update_details = {
        'text': f"Downloading: {{0}} {{1}}/{{2}}\n{{3}} ({{4}})", 
        'msg': user['bot_msg'], 
        'title': album_meta['title'], 'type': 'album'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    album_meta['tracks'] = successful_tracks
    
    if successful_tracks:
        LOGGER.info(f"[HANDLER FINAL] Tracks Ready. Sample: {successful_tracks[0]['filepath']}")
        if filter_track_id and len(successful_tracks) == 1:
            track_data = successful_tracks[0]
            album_meta.update(track_data)
            album_meta['tracks'] = successful_tracks
            album_meta['type'] = 'album'
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
        if meta.get('totaltracks'): audio['TRACKTOTAL'] = str(meta.get('totaltracks')); audio['TOTALTRACKS'] = str(meta.get('totaltracks'))
        if meta.get('date'): audio['DATE'] = str(meta.get('date')); audio['ORIGINALDATE'] = str(meta.get('date'))
        if meta.get('label'): audio['ORGANIZATION'] = meta.get('label', ''); audio['LABEL'] = meta.get('label', '')
        if lyrics and isinstance(lyrics, str) and len(lyrics) > 10: audio['LYRICS'] = lyrics; audio['UNSYNCEDLYRICS'] = lyrics 
        if cover_path and os.path.exists(cover_path):
            p = Picture()
            with open(cover_path, 'rb') as f: p.data = f.read()
            p.type = 3; p.mime = 'image/jpeg'; p.desc = 'Front Cover'
            audio.add_picture(p)
        audio.save()
        return int(audio.info.length)
    except Exception: return 0

async def _download_quality_variant(meta, user, folderpath, quality_code):
    client = user['moov_api']
    track_temp_dir = os.path.join(folderpath, f"temp_{meta['itemid']}")
    
    try:
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        os.makedirs(track_temp_dir, exist_ok=True)
        
        # 1. INIT
        try:
            file_meta = await client.get_track_file_meta(meta['itemid'], quality_code)
            play_url_init = file_meta.get('playUrl')
            content_key = file_meta.get('contentKey')
            if not play_url_init or not content_key: return False
            m = hashlib.md5()
            m.update((content_key + SECRET_SALT).encode('UTF-8'))
            default_key_bytes = bytes.fromhex(m.hexdigest())
        except: return False

        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, meta, user)
        safe_filename = safe_name(raw_filename)
        final_filepath = os.path.join(folderpath, f"{safe_filename}.flac")
        abs_path = os.path.abspath(final_filepath)
        meta['filepath'] = abs_path
        meta['file_path'] = abs_path
        meta['path'] = abs_path
        meta['file'] = abs_path
        meta['outfile'] = abs_path
        meta['filename'] = os.path.basename(abs_path)
        meta['is_downloaded'] = True
        meta['success'] = True
        
        # [FIX] Rename key to .m4a to bypass FFmpeg security block
        key_filepath = os.path.join(track_temp_dir, "key.m4a")
        async with aiofiles.open(key_filepath, 'wb') as f:
            await f.write(default_key_bytes)

        # 2. COVER
        cover_local_path = None
        target_url = meta.get('cover_url')
        if target_url:
            cover_local_path = os.path.join(track_temp_dir, "cover.jpg")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            async with aiofiles.open(cover_local_path, 'wb') as f: await f.write(data)
                        else: cover_local_path = None
            except: cover_local_path = None
        if not cover_local_path and meta.get('cover') and os.path.exists(meta.get('cover')):
            cover_local_path = os.path.join(track_temp_dir, "cover_fallback.jpg")
            shutil.copy(meta['cover'], cover_local_path)

        # 3. LOOP UTAMA
        success_process = False
        play_url = play_url_init
        
        for attempt in range(2):
            use_proxy = (attempt == 0)
            
            # Setup Session
            if not use_proxy:
                LOGGER.info(f"Fallback to DIRECT connection (Attempt {attempt})...")
                jar = aiohttp.CookieJar(unsafe=True)
                if client.session.cookie_jar:
                    for cookie in client.session.cookie_jar:
                        jar.update_cookies({cookie.key: cookie.value}, response_url=URL('https://moov.hk'))
                connector = aiohttp.TCPConnector(ssl=False)
                session_context = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
            else:
                session_context = client.session

            try:
                async with (session_context if not use_proxy else asyncio.NullContext()) as session:
                    sess = client.session if use_proxy else session_context

                    # A. Fetch M3U8
                    try:
                        async with sess.get(play_url, headers=BROWSER_HEADERS) as resp:
                            if resp.status != 200: 
                                if not use_proxy: break
                                continue
                            m3u8_content = await resp.text()
                    except: continue

                    if "#EXT-X-STREAM-INF" in m3u8_content:
                        remote_lines = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
                        if remote_lines:
                            play_url = merge_urls(play_url, remote_lines[0])
                            continue 

                    # B. Parse & Download Resources
                    local_m3u8_path = os.path.join(track_temp_dir, "local.m3u8")
                    remote_segments = []
                    error_in_parsing = False

                    async with aiofiles.open(local_m3u8_path, 'w') as f_out:
                        seg_idx = 0
                        for line in m3u8_content.splitlines():
                            line = line.strip()
                            if not line: continue
                            
                            # Handle Key
                            if line.startswith("#EXT-X-KEY"):
                                key_match = re.search(r'URI="([^"]+)"', line)
                                if key_match:
                                    raw_key_uri = key_match.group(1)
                                    if '?' in raw_key_uri:
                                        key_uri = resolve_url(play_url, raw_key_uri)
                                    else:
                                        key_uri = merge_urls(play_url, raw_key_uri)
                                    
                                    if not await download_resource(sess, key_uri, key_filepath):
                                        LOGGER.warning("Key DL Failed.")
                                        error_in_parsing = True
                                        break
                                    
                                    # [FIX] Gunakan key.m4a
                                    new_line = re.sub(r'URI="[^"]+"', 'URI="key.m4a"', line)
                                    await f_out.write(f"{new_line}\n")
                                else:
                                    await f_out.write(f"{line}\n")

                            # Handle Map
                            elif line.startswith("#EXT-X-MAP"):
                                map_match = re.search(r'URI="([^"]+)"', line)
                                if map_match:
                                    raw_map_uri = map_match.group(1)
                                    if '?' in raw_map_uri:
                                        map_uri = resolve_url(play_url, raw_map_uri)
                                    else:
                                        map_uri = merge_urls(play_url, raw_map_uri)
                                    
                                    # [FIX] Rename map to init.m4a
                                    map_path = os.path.join(track_temp_dir, "init.m4a")
                                    if not await download_resource(sess, map_uri, map_path):
                                        LOGGER.warning("Map DL Failed.")
                                        error_in_parsing = True
                                        break
                                    
                                    new_line = re.sub(r'URI="[^"]+"', 'URI="init.m4a"', line)
                                    await f_out.write(f"{new_line}\n")
                                else:
                                    await f_out.write(f"{line}\n")
                            
                            elif line.startswith("#"):
                                await f_out.write(f"{line}\n")
                            
                            else:
                                remote_segments.append(line)
                                # [FIX] Rename segments to .m4a
                                seg_filename = f"seg_{seg_idx:04d}.m4a"
                                await f_out.write(f"{seg_filename}\n")
                                seg_idx += 1
                    
                    if error_in_parsing: 
                        if use_proxy: continue 
                        else: break

                    # D. Download Segments
                    seg_error = False
                    for index, seg_url_raw in enumerate(remote_segments):
                        seg_url = merge_urls(play_url, seg_url_raw)
                        # [FIX] Rename local segment path to .m4a
                        seg_path = os.path.join(track_temp_dir, f"seg_{index:04d}.m4a")
                        
                        if not await download_resource(sess, seg_url, seg_path):
                            seg_error = True
                            break
                    
                    if seg_error: continue 
                    
                    success_process = True
                    break 

            except Exception as e:
                LOGGER.error(f"Loop Error: {e}")
                continue

        if not success_process: return False

        # 4. FFMPEG Processing
        cmd = [
            'ffmpeg', '-y',
            '-analyzeduration', '100M', '-probesize', '100M',
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
            LOGGER.warning(f"FFmpeg encode error, trying copy...")
            cmd[7] = 'copy' 
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                LOGGER.error(f"FFmpeg Fail: {stderr.decode()}")
                return False

        if not os.path.exists(final_filepath) or os.path.getsize(final_filepath) < 100:
            return False
            
        meta['filesize'] = os.path.getsize(final_filepath)

        # 5. TAGS & CLEANUP
        lyrics_text = None
        try:
            track_id = str(meta.get('itemid', ''))
            if track_id: lyrics_text = await client.get_lyrics(track_id)
        except: pass

        real_duration = await apply_mutagen_tags(final_filepath, meta, cover_local_path, lyrics=lyrics_text)
        if real_duration > 0: meta['duration'] = real_duration
            
        if cover_local_path and os.path.exists(cover_local_path):
            album_cover_path = os.path.join(folderpath, "cover.jpg")
            if not os.path.exists(album_cover_path): shutil.copy(cover_local_path, album_cover_path)
            meta['cover'] = album_cover_path
        else: meta['cover'] = None
        
        if lyrics_text and isinstance(lyrics_text, str):
            try:
                lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
                async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f: await f.write(lyrics_text)
            except: pass

        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return True

    except Exception as e:
        LOGGER.error(f"Download Variant Error ({quality_code}): {e}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False

# Dummy nullcontext
if not hasattr(asyncio, 'NullContext'):
    class NullContext:
        async def __aenter__(self): return None
        async def __aexit__(self, *args): pass
    asyncio.NullContext = NullContext

async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    target_q = meta.get('moov_quality_code', 'LL')
    qualities_to_try = ['HR', 'LL'] if target_q == 'HR' else ['LL', 'HR']

    for quality in qualities_to_try:
        LOGGER.info(f"Mencoba download {meta.get('title')} dengan kualitas: {quality}")
        success = await _download_quality_variant(meta, user, folderpath, quality)
        if success:
            LOGGER.info(f"Berhasil download {meta.get('title')} ({quality})")
            return meta
    
    LOGGER.error(f"Gagal mendownload {meta.get('title')} pada semua kualitas.")
    return False
