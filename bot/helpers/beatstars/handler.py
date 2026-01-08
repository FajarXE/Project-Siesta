# [GANTI FILE: bot/helpers/beatstars/handler.py]

import os
import re
import aiohttp
import asyncio
import shutil # Tambahan import
from datetime import datetime
from urllib.parse import urlparse
from bot.logger import LOGGER
from bot.helpers.uploder import track_upload, artist_upload, album_upload
from bot.helpers.metadata import set_metadata
from bot.helpers.utils import post_art_poster, zip_handler, fetch_zip_settings

try:
    from mutagen.id3 import ID3, TPE2, COMM, TSSE, TENC
except ImportError:
    ID3, TPE2, COMM, TSSE, TENC = None, None, None, None, None

ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", 
    "x-algolia-application-id": "NMMGZJQ6QI",
    "Origin": "https://www.beatstars.com",
    "Referer": "https://www.beatstars.com/",
    "Connection": "keep-alive",
}

PLACEHOLDER_COVER = "https://www.beatstars.com/assets/img/placeholder-track.png"

def parse_metadata_rich(data_list, tags_list=None, bpm=None):
    extracted = []
    if data_list:
        iterable = data_list.values() if isinstance(data_list, dict) else data_list
        for item in iterable:
            if isinstance(item, str): extracted.append(item)
            elif isinstance(item, dict):
                name = item.get('name') or item.get('slug') or item.get('title')
                if name: extracted.append(str(name))
    if tags_list:
        if isinstance(tags_list, list):
            for tag in tags_list[:5]: 
                tag_name = tag if isinstance(tag, str) else tag.get('name', '')
                if tag_name and tag_name not in extracted: extracted.append(tag_name)
    if bpm: extracted.append(f"{bpm} BPM")
    return ", ".join(extracted) if extracted else "BeatStars"

def format_date(timestamp):
    try:
        if not timestamp: return ""
        dt_object = datetime.fromtimestamp(int(timestamp))
        return dt_object.strftime("%Y-%m-%d")
    except: return str(timestamp)

def clean_cover_url(url):
    if not url: return None
    url = url.replace(r'\/', '/')
    if "://" not in url and "//" in url: url = url.replace("//", "/")
    return url

def patch_metadata_manual(filepath, album_artist):
    """ Hanya dijalankan jika file adalah MP3 """
    if not filepath.lower().endswith('.mp3'):
        return # Skip untuk WAV/FLAC

    if not ID3: return
    try:
        audio = ID3(filepath)
        keys_to_delete = []
        for key in audio.keys():
            if key.startswith("COMM") or key.startswith("TENC") or key.startswith("TSSE") or key.startswith("TXXX"):
                keys_to_delete.append(key)
                continue
            frame = audio[key]
            if hasattr(frame, 'text'): 
                for text_val in frame.text:
                    if "processed by" in str(text_val).lower() or "sox" in str(text_val).lower():
                        keys_to_delete.append(key)
                        break
        for key in list(set(keys_to_delete)):
            if key in audio: del audio[key]

        if album_artist: audio.add(TPE2(encoding=3, text=str(album_artist)))
        audio.save(v2_version=3, v1=2)
        LOGGER.info("[Patch] Metadata bersih (MP3 Only).")
    except Exception as e:
        LOGGER.error(f"Gagal patching metadata manual: {e}")

async def download_local_cover(session, url, folderpath):
    if not url: return PLACEHOLDER_COVER
    filename = "cover.jpg"
    filepath = os.path.join(folderpath, filename)
    try:
        async with session.get(url, allow_redirects=True, timeout=15) as resp:
            if resp.status == 200:
                content = await resp.read()
                if not content: return PLACEHOLDER_COVER
                with open(filepath, 'wb') as f: f.write(content)
                return filepath
            else: return PLACEHOLDER_COVER
    except: return PLACEHOLDER_COVER


# --- REVISI: DOWNLOADER DENGAN DETEKSI KONTEN ---
async def download_beatstars_file(url, path):
    """
    Mengunduh file dan mendeteksi ekstensi asli (WAV/MP3).
    Mengembalikan: (error_string, detected_extension)
    """
    final_ext = '.mp3' # Default
    try:
        folder = os.path.dirname(path)
        if folder: os.makedirs(folder, exist_ok=True)

        async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    # --- DETEKSI TIPE KONTEN ---
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'wav' in content_type:
                        final_ext = '.wav'
                    # ---------------------------

                    with open(path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024 * 4)
                            if not chunk: break
                            f.write(chunk)
                    
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        return None, final_ext
                    else:
                        return "File kosong", final_ext
                else:
                    return f"HTTP Status: {response.status}", final_ext
    except Exception as e:
        return str(e), final_ext


async def start_beatstars(link: str, user: dict):
    parsed = urlparse(link)
    path = parsed.path.strip("/")
    path_parts = path.split("/")

    if path.startswith("beat/") or "/beat/" in link:
        track_regex = r'(\d+)$'
        track_match = re.search(track_regex, path)
        if track_match:
            track_id = track_match.group(1)
            LOGGER.info(f"BeatStars Track Mode: ID {track_id}")
            await process_single_track(user, track_id)
        else:
            raise Exception("Link Beat tidak valid: Tidak dapat menemukan ID Lagu.")
    else:
        if not path_parts or not path_parts[0]:
             raise Exception("Link tidak valid.")
        permalink = path_parts[0]
        reserved_words = ['beat', 'tracks', 'feed', 'services', 'publishing', 'dashboard', 'playlists', 'collection', 'musician']
        if permalink.lower() in reserved_words:
             raise Exception(f"Link tidak valid: '{permalink}' adalah halaman sistem.")
        LOGGER.info(f"BeatStars Artist Mode: {permalink}")
        await process_artist(user, permalink)


async def process_single_track(user, track_id):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        async with session.get(url) as resp:
            if resp.status != 200: raise Exception(f"BeatStars API Error: {resp.status}")
            data = await resp.json()
    
        if not data.get('response', {}).get('data'): raise Exception("Track tidak ditemukan.")

        details = data['response']['data']['details']
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
        if not os.path.exists(folderpath): os.makedirs(folderpath, exist_ok=True)

        raw_cover = details.get('artwork', {}).get('original')
        clean_url = clean_cover_url(raw_cover)
        local_cover_path = await download_local_cover(session, clean_url, folderpath)

        release_date_fmt = format_date(details.get('release_date_time', 0))
        artist_name = details.get('musician', {}).get('display_name')
        track_title = details.get('title')
        bpm = details.get('bpm', 0)
        tags = details.get('tags', []) 
        duration_ms = details.get('duration', 0)
        
        copyright_txt = details.get('copyright', '') 
        if not copyright_txt:
            year = release_date_fmt[:4] if release_date_fmt else "2024"
            copyright_txt = f"© {year} {artist_name}"

        rich_genre = parse_metadata_rich(details.get('genre', []), tags, bpm)

        # Nama file sementara (default mp3)
        filename_base = f"{artist_name} - {track_title}"
        filename_base = re.sub(r'[\\/*?:"<>|]', "", filename_base)
        temp_filepath = f"{folderpath}/{filename_base}.mp3"

        stream_url = details.get('stream_url')
        if not stream_url:
            stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

        LOGGER.info(f"Downloading Single Track: {track_title}")
        
        # Download dan dapatkan ekstensi asli
        err, real_ext = await download_beatstars_file(stream_url, temp_filepath)
        if err: raise Exception(f"Gagal download file: {err}")

        # Rename jika ternyata WAV
        final_filepath = temp_filepath
        if real_ext == '.wav':
            new_path = f"{folderpath}/{filename_base}.wav"
            shutil.move(temp_filepath, new_path)
            final_filepath = new_path
            LOGGER.info(f"Format terdeteksi WAV, renaming ke: {os.path.basename(final_filepath)}")

        meta = {
            'title': track_title,
            'artist': artist_name,
            'albumartist': artist_name,
            'performer': artist_name,
            'composer': artist_name,
            'album': f"{artist_name} - Singles",
            'tracknumber': 1,
            'totaltracks': 1,
            'volume': 1,
            'totalvolume': 1,
            'copyright': copyright_txt,
            'isrc': '',
            'release_date': release_date_fmt,
            'date': release_date_fmt[:4] if release_date_fmt else '',
            'cover': local_cover_path,
            'provider': 'BeatStars',
            'type': 'track', 
            'itemid': str(details.get('track_id')),
            'genre': rich_genre,
            'duration': str(duration_ms), 
            'explicit': False,
            'filepath': final_filepath, # Path final
            'folderpath': folderpath,
            'extension': real_ext.replace('.', '') # wav/mp3
        }

    await set_metadata(meta, user['user_id'])
    # Patch manual hanya jika MP3 (diurus di dalam fungsi)
    patch_metadata_manual(final_filepath, artist_name)
    await track_upload(meta, user)


async def process_artist(user, permalink):
    # ... (Bagian awal sama) ...
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
        async with session.get(artist_url) as resp:
            if resp.status != 200: raise Exception(f"Gagal mengambil profil artis: {resp.status}")
            artist_data = await resp.json()
        
        try: user_id_num = int(artist_data['response']['data']['profile']['user_id'])
        except: raise Exception("Profil artis tidak valid.")
        member_id = f"MR{user_id_num}"
        query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
        
        all_tracks = []
        page = 0
        await user['bot_msg'].edit(f"Mengambil daftar lagu: {permalink}...")
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
        if not os.path.exists(folderpath): os.makedirs(folderpath, exist_ok=True)
        
        while True:
            payload = { "query": "", "page": page, "hitsPerPage": 1000, "facets": ["*"], "facetFilters": [[f"profile.memberId:{member_id}"]], "maxValuesPerFacet": 1000 }
            async with session.post(query_url, json=payload) as resp:
                if resp.status != 200: break
                search_res = await resp.json()
            hits = search_res.get('hits', [])
            if not hits: break
            
            for hit in hits:
                track_id = hit.get('v2Id')
                stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
                raw_cover = hit.get('artwork', {}).get('sizes', {}).get('original')
                clean_url = clean_cover_url(raw_cover)
                ts = hit.get('releaseTimestamp') or hit.get('releaseDate') or 0
                date_fmt = format_date(ts)
                artist_name = hit.get('metadata', {}).get('artistName')
                bpm = hit.get('metadata', {}).get('bpm', 0)
                tags = hit.get('metadata', {}).get('tags', [])
                rich_genre = parse_metadata_rich(hit.get('metadata', {}).get('genres', []), tags, bpm)
                copyright_txt = f"© {date_fmt[:4] if date_fmt else '2024'} {artist_name}"

                all_tracks.append({
                    'title': hit.get('title'),
                    'artist': artist_name,
                    'albumartist': artist_name,
                    'performer': artist_name,
                    'composer': artist_name,
                    'album': f"{artist_name} - BeatStars Collection",
                    'cover': clean_url,
                    'itemid': str(track_id),
                    'url': stream_url,
                    'genre': rich_genre,
                    'copyright': copyright_txt, 
                    'isrc': '',
                    'volume': 1,
                    'totalvolume': 1,
                    'duration': str(hit.get('duration', '')),
                    'explicit': False,
                    'release_date': date_fmt,
                    'date': date_fmt[:4] if date_fmt else '',
                })
            page += 1
            if page >= search_res.get('nbPages', 0): break

    if not all_tracks: raise Exception("Tidak ada track ditemukan.")

    album_meta = {
        'type': 'album', 'title': f"Tracks by {permalink}", 'artist': all_tracks[0]['artist'],
        'albumartist': all_tracks[0]['artist'], 'cover': all_tracks[0]['cover'], 'provider': 'BeatStars',
        'folderpath': folderpath, 'poster_msg': None, 'zip_path': None, 'tracks': []
    }
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    if art_poster: album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    await user['bot_msg'].edit(f"Ditemukan {len(all_tracks)} track. Memulai unduhan...")
    total_items = len(all_tracks)
    
    for i, t in enumerate(all_tracks):
        try:
            filename_base = f"{t['artist']} - {t['title']}"
            filename_base = re.sub(r'[\\/*?:"<>|]', "", filename_base)
            temp_filepath = f"{folderpath}/{filename_base}.mp3"
            
            if i % 5 == 0:
                try: await user['bot_msg'].edit(f"Mengunduh {i+1}/{total_items}: {t['title']}")
                except: pass

            err, real_ext = await download_beatstars_file(t['url'], temp_filepath)
            if err: continue
            
            # Rename WAV
            final_filepath = temp_filepath
            if real_ext == '.wav':
                new_path = f"{folderpath}/{filename_base}.wav"
                shutil.move(temp_filepath, new_path)
                final_filepath = new_path

            t['filepath'] = final_filepath
            t['folderpath'] = folderpath
            t['tracknumber'] = i + 1
            t['totaltracks'] = total_items
            t['type'] = 'track'
            
            local_cov = await download_local_cover(session, t['cover'], folderpath)
            t['cover'] = local_cov

            await set_metadata(t, user['user_id'])
            patch_metadata_manual(final_filepath, t['albumartist']) # Safe inside
            album_meta['tracks'].append(t)
        except Exception as e:
            LOGGER.error(f"Error track {t['title']}: {e}")

    if not album_meta['tracks']: raise Exception("Gagal mengunduh semua track.")
    if artist_zip or album_zip or playlist_zip:
        await user['bot_msg'].edit("Sedang membuat file Zip...")
        album_meta['zip_path'] = await zip_handler(folderpath)

    await album_upload(album_meta, user)
