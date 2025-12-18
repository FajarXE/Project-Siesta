# [GANTI FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
import traceback
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, TPOS, TCON, TPUB, TCOP, TDRC, APIC, USLT
from config import Config
from bot.logger import LOGGER
from ..message import edit_message
from .metadata import process_album_metadata, process_playlist_metadata, process_track_metadata
from ..uploder import album_upload, playlist_upload
from ..utils import (
    format_string, run_concurrent_tasks, zip_handler, 
    fetch_zip_settings, post_art_poster
)

SECRET_SALT = "F4:8E:09:CE:54:F7SeCrEtKkK"

def safe_name(name):
    return re.sub(r'[\/:*?"><|#]', '_', str(name)).strip()

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

    elif "/chart/" in clean_url or "/playlist/" in clean_url:
        if "/chart/" in clean_url:
            raw_id = clean_url.split("/chart/")[-1]
        else:
            raw_id = clean_url.split("/playlist/")[-1]
            
        pid = raw_id.split("?")[0].split("/")[0]
        LOGGER.info(f"Moov: Terdeteksi Chart/Playlist ID: {pid}")
        await start_playlist(pid, user)

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
        raise Exception("Link Moov tidak dikenali. Mendukung: Album, Lagu, Chart, Playlist, dan Share Link.")

async def start_track_single(track_id, user):
    client = user['moov_api']
    try:
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

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    
    album_meta['folderpath'] = album_folder

    if upload and not filter_track_id:
        try:
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
        except Exception as e:
            LOGGER.error(f"Poster Error (Ignored): {e}")

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(download_track_retry_wrapper(track, user, album_folder))

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

async def enrich_and_download_chart_track(shallow_track_meta, user, folderpath, album_cache):
    client = user['moov_api']
    track_id = shallow_track_meta.get('itemid')
    
    full_product = None
    album_id = None

    try:
        full_product = await client.get_product_meta(track_id)
        if full_product:
            album_id = full_product.get('albumId') or full_product.get('album', {}).get('id')
        else:
            LOGGER.warning(f"Moov: Product {track_id} gagal (404/Null), menggunakan data Shallow.")
    except Exception:
        LOGGER.warning(f"Moov: Exception saat ambil product {track_id}.")

    if not album_id:
        album_id = shallow_track_meta.get('moov_album_id')

    album_meta_full = None
    if album_id:
        if album_id in album_cache:
            album_meta_full = album_cache[album_id]
        else:
            try:
                raw_album = await client.get_album_meta(album_id)
                if raw_album:
                    album_meta_full = await process_album_metadata(raw_album, user['r_id'], user)
                    album_cache[album_id] = album_meta_full 
            except Exception as e:
                LOGGER.warning(f"Gagal fetch album context {album_id}: {e}")

    deep_meta = None

    if full_product:
        deep_meta = await process_track_metadata(
            full_product, 
            user['r_id'], 
            user, 
            cover=album_meta_full['cover'] if album_meta_full else None,
            album_meta=album_meta_full if album_meta_full else None
        )
    else:
        deep_meta = shallow_track_meta.copy()
        
        # INJECT DATA ALBUM (FALLBACK)
        if album_meta_full:
            if album_meta_full.get('cover'):
                deep_meta['cover'] = album_meta_full['cover']
                deep_meta['cover_url'] = None 
                
            if album_meta_full.get('label'):
                deep_meta['label'] = album_meta_full['label']
            if album_meta_full.get('date'):
                deep_meta['date'] = album_meta_full['date']
                deep_meta['year'] = album_meta_full['year']
            if album_meta_full.get('copyright'):
                deep_meta['copyright'] = album_meta_full['copyright']
            if album_meta_full.get('totaltracks'):
                deep_meta['totaltracks'] = album_meta_full['totaltracks']
            if album_meta_full.get('totalvolumes'):
                deep_meta['totalvolumes'] = album_meta_full['totalvolumes']

    deep_meta['folderpath'] = folderpath
    return await download_track_retry_wrapper(deep_meta, user, folderpath)

async def start_playlist(pid, user):
    client = user['moov_api']
    try:
        raw_data = await client.get_playlist_meta(pid)
        if not raw_data: raise Exception("Metadata playlist/chart kosong.")
        pl_meta = await process_playlist_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata Playlist/Chart: {e}")

    if not pl_meta.get('tracks'):
         raise Exception("Playlist/Chart ini kosong atau format tidak didukung.")

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_title = safe_name(pl_meta['title'])
    pl_folder = os.path.join(base_dir, str(user['r_id']), "Moov", "Playlists", safe_title)
    pl_meta['folderpath'] = pl_folder

    try:
        pl_meta['poster_msg'] = await post_art_poster(user, pl_meta)
    except: pass

    album_cache = {} 
    tasks = []
    
    for track in pl_meta['tracks']:
        tasks.append(enrich_and_download_chart_track(track, user, pl_folder, album_cache))

    update_details = {
        'text': f"Downloading Playlist: {{0}} {{1}}/{{2}}\n{{3}} ({{4}})", 
        'msg': user['bot_msg'], 
        'title': pl_meta['title'], 'type': 'playlist'
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    
    pl_meta['tracks'] = successful_tracks
    if not successful_tracks:
        raise Exception("Gagal mengunduh semua lagu dari Playlist ini (Cek Log untuk detail).")

    try:
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
        if playlist_zip: 
            await edit_message(user['bot_msg'], "Zipping...")
            pl_meta['zip_path'] = await zip_handler(pl_meta['folderpath'])
    except Exception as e:
        LOGGER.error(f"Zip Error: {e}")
        
    await edit_message(user['bot_msg'], "Uploading...")
    await playlist_upload(pl_meta, user)

async def apply_mutagen_tags(filepath, meta, cover_path, lyrics=None):
    try:
        ext = meta.get('extension', 'flac')
        
        if ext == 'flac':
            audio = FLAC(filepath)
            audio.delete() 
            
            audio['TITLE'] = meta.get('title', '')
            audio['ARTIST'] = meta.get('artist', '')
            audio['PERFORMER'] = meta.get('artist', '') 
            audio['ALBUMARTIST'] = meta.get('albumartist', '')
            audio['ALBUM'] = meta.get('album', '')
            audio['GENRE'] = meta.get('genre', '')
            audio['COMPOSER'] = meta.get('composer', '')
            if meta.get('producer'): audio['PRODUCER'] = meta.get('producer')
            audio['COPYRIGHT'] = meta.get('copyright', '')
            audio['DISCNUMBER'] = str(meta.get('disk', ''))
            audio['TRACKNUMBER'] = str(meta.get('tracknumber', ''))
            
            if meta.get('totaltracks'):
                audio['TRACKTOTAL'] = str(meta.get('totaltracks'))
                audio['TOTALTRACKS'] = str(meta.get('totaltracks'))
            if meta.get('date'):
                audio['DATE'] = str(meta.get('date'))
                audio['YEAR'] = str(meta.get('date'))[:4]
                audio['ORIGINALDATE'] = str(meta.get('date'))
                audio['RELEASEDATE'] = str(meta.get('date')) 
                audio['RECORDEDDATE'] = str(meta.get('date')) 
            if meta.get('label'):
                audio['ORGANIZATION'] = meta.get('label', '')
                audio['LABEL'] = meta.get('label', '')
                audio['PUBLISHER'] = meta.get('label', '') 

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
        
        elif ext == 'mp3':
            try: audio = ID3(filepath)
            except: audio = ID3()
            
            audio.add(TIT2(encoding=3, text=meta.get('title', '')))
            audio.add(TPE1(encoding=3, text=meta.get('artist', '')))
            audio.add(TALB(encoding=3, text=meta.get('album', '')))
            audio.add(TRCK(encoding=3, text=f"{meta.get('tracknumber', '')}/{meta.get('totaltracks', '')}"))
            audio.add(TPOS(encoding=3, text=str(meta.get('disk', ''))))
            audio.add(TCON(encoding=3, text=meta.get('genre', '')))
            audio.add(TPUB(encoding=3, text=meta.get('label', '')))
            audio.add(TCOP(encoding=3, text=meta.get('copyright', '')))
            if meta.get('date'):
                audio.add(TDRC(encoding=3, text=str(meta.get('date'))[:4]))
            if lyrics and isinstance(lyrics, str):
                audio.add(USLT(encoding=3, lang='eng', desc='desc', text=lyrics))
            if cover_path and os.path.exists(cover_path):
                with open(cover_path, 'rb') as f:
                    audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=f.read()))
            audio.save(filepath)
            return 0 

    except Exception as e:
        LOGGER.error(f"Mutagen Error ({ext}): {e}")
        return 0

async def download_track_retry_wrapper(track_meta, user, folderpath):
    result = await download_track(track_meta, user, folderpath)
    
    if result is False:
        current_quality = track_meta.get('moov_quality_code', 'LL')
        if current_quality != 'MP3_320':
            LOGGER.warning(f"Moov: Download FLAC gagal total untuk {track_meta.get('title')}. Mencoba FALLBACK ke MP3...")
            fallback_meta = track_meta.copy()
            fallback_meta['moov_quality_code'] = 'MP3_320'
            fallback_meta['extension'] = 'mp3'
            fallback_meta['quality'] = 'MP3 320kbps'
            return await download_track(fallback_meta, user, folderpath)
    return result

async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    client = user['moov_api']
    
    if not meta.get('itemid'): return False

    file_meta = None
    target_quality = meta.get('moov_quality_code', 'LL')
    if target_quality == 'MP3_320': target_quality = 'HQ'

    try:
        file_meta = await client.get_track_file_meta(meta['itemid'], target_quality)
    except Exception as e:
        LOGGER.warning(f"Moov Stream Check Error ({target_quality}): {e}")

    if not file_meta and target_quality not in ['LL', 'HQ']:
        LOGGER.info(f"Moov: Kualitas {target_quality} tidak tersedia, fallback ke LL...")
        target_quality = 'LL'
        try:
            file_meta = await client.get_track_file_meta(meta['itemid'], 'LL')
            if file_meta: meta['quality'] = 'FLAC 16bit' 
        except: pass

    if not file_meta:
        return False
        
    play_url = file_meta.get('playUrl')
    content_key = file_meta.get('contentKey')
    if not play_url: return False

    key_bytes = None
    try:
        if content_key:
            m = hashlib.md5()
            m.update((content_key + SECRET_SALT).encode('UTF-8'))
            key_bytes = bytes.fromhex(m.hexdigest())
    except: return False

    track_temp_dir = os.path.join(folderpath, f"temp_{meta['itemid']}")
    try:
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, meta, user)
        safe_filename = safe_name(raw_filename)
        
        ext = meta.get('extension', 'flac')
        if target_quality == 'HQ': ext = 'mp3'
        meta['extension'] = ext

        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        os.makedirs(track_temp_dir, exist_ok=True)

        final_filepath = os.path.join(folderpath, f"{safe_filename}.{ext}")
        
        abs_path = os.path.abspath(final_filepath)
        meta['filepath'] = abs_path
        meta['filename'] = os.path.basename(abs_path)
        meta['is_downloaded'] = True
        
        if key_bytes:
            key_filepath = os.path.join(track_temp_dir, "key.bin")
            async with aiofiles.open(key_filepath, 'wb') as f:
                await f.write(key_bytes)

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
                        else: cover_local_path = None
            except: cover_local_path = None
        
        if not cover_local_path and meta.get('cover') and os.path.exists(meta.get('cover')):
            cover_local_path = os.path.join(track_temp_dir, "cover_fallback.jpg")
            shutil.copy(meta['cover'], cover_local_path)

        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        m3u8_content = None
        
        for _ in range(3): 
            try:
                async with client.session.get(play_url, headers=hls_headers) as resp:
                    if resp.status == 200: 
                        m3u8_content = await resp.text()
                        break
                    else:
                        await asyncio.sleep(2) 
            except:
                await asyncio.sleep(2)
        
        if not m3u8_content:
            shutil.rmtree(track_temp_dir)
            return False

        target_duration = 10
        media_sequence = 0
        original_iv_line = ""
        # Simpan info IV asli jika ada
        if "#EXT-X-KEY" in m3u8_content:
            iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', m3u8_content)
            if iv_match: original_iv_line = f",IV=0x{iv_match.group(1)}"

        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-TARGETDURATION"):
                target_duration = line.split(":")[1].strip()
            if line.startswith("#EXT-X-MEDIA-SEQUENCE"):
                media_sequence = int(line.split(":")[1].strip())

        remote_segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        local_segment_names = []
        
        first_segment_path = None

        for index, seg_url in enumerate(remote_segments):
            seg_name = f"seg_{index:04d}.{ext}" 
            seg_path = os.path.join(track_temp_dir, seg_name)
            local_segment_names.append(seg_name)
            if index == 0: first_segment_path = seg_path
            
            success = False
            for _ in range(3):
                try:
                    async with client.session.get(seg_url, headers=hls_headers) as seg_resp:
                        if seg_resp.status == 200:
                            data = await seg_resp.read()
                            if len(data) < 500: raise Exception("Small")
                            async with aiofiles.open(seg_path, 'wb') as f:
                                await f.write(data)
                            success = True
                            break
                except: continue
            
            if not success:
                shutil.rmtree(track_temp_dir)
                return False

        # --- SMART ENCRYPTION CHECK (ANTI-GAGAL) ---
        is_encrypted = False
        
        # 1. Cek Magic Bytes segmen pertama
        if first_segment_path and os.path.exists(first_segment_path):
            async with aiofiles.open(first_segment_path, 'rb') as f:
                header = await f.read(4)
                # Jika header file adalah Clear Audio (FLAC/ID3/AAC), maka TIDAK terenkripsi
                if header.startswith(b'fLaC'): is_encrypted = False 
                elif header.startswith(b'ID3') or header.startswith(b'\xff\xfb'): is_encrypted = False 
                elif header.startswith(b'ADIF') or header.startswith(b'\xff\xf1'): is_encrypted = False 
                else: 
                    # Header acak = Terenkripsi
                    is_encrypted = True 
        
        if not content_key: is_encrypted = False

        # Build Local M3U8
        local_m3u8_path = os.path.join(track_temp_dir, "local.m3u8")
        key_line = ""
        if is_encrypted:
            key_line = f'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"{original_iv_line}\n'
            
        async with aiofiles.open(local_m3u8_path, 'w') as f:
            await f.write("#EXTM3U\n")
            await f.write("#EXT-X-VERSION:3\n")
            await f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
            await f.write(f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}\n")
            await f.write(key_line)
            for seg_name in local_segment_names:
                await f.write(f"#EXTINF:{target_duration},\n")
                await f.write(f"{seg_name}\n")
            await f.write("#EXT-X-ENDLIST\n")

        # --- FFMPEG SAFE TRANSCODE ---
        # Jika MP3, gunakan encoding ulang (libmp3lame) untuk menghindari error copy
        # Jika FLAC, gunakan flac
        audio_codec = 'flac'
        if ext == 'mp3': audio_codec = 'libmp3lame'

        cmd = [
            'ffmpeg', '-y',
            '-allowed_extensions', 'ALL',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-analyzeduration', '10000000',
            '-probesize', '10000000',      
            '-i', local_m3u8_path,
            '-c:a', audio_codec, # Gunakan encoder aman, bukan copy
            '-q:a', '0',         # Kualitas terbaik untuk MP3
            final_filepath
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode != 0:
            LOGGER.error(f"FFmpeg Error ({ext}): {stderr.decode()}")
            shutil.rmtree(track_temp_dir)
            return False 

        if not os.path.exists(final_filepath) or os.path.getsize(final_filepath) == 0:
            return False
            
        meta['filesize'] = os.path.getsize(final_filepath)

        lyrics_text = None
        try:
            track_id = str(meta.get('itemid', ''))
            if track_id: lyrics_text = await client.get_lyrics(track_id)
        except: pass

        real_duration = await apply_mutagen_tags(final_filepath, meta, cover_local_path, lyrics=lyrics_text)
        if real_duration > 0: meta['duration'] = real_duration
            
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
        LOGGER.error(f"DL Crash: {e}\n{traceback.format_exc()}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False
        
    return meta
