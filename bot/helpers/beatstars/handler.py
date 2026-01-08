# [GANTI FILE: bot/helpers/beatstars/handler.py]

import os
import re
import aiohttp
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from bot.logger import LOGGER
from bot.helpers.uploder import track_upload, artist_upload, album_upload
from bot.helpers.metadata import set_metadata
from bot.helpers.utils import post_art_poster, zip_handler, fetch_zip_settings

# Import Mutagen
try:
    from mutagen.id3 import ID3, TPE2, COMM, TSSE, TENC
except ImportError:
    LOGGER.error("Mutagen belum terinstall. Fitur patching metadata tidak akan berjalan.")
    ID3, TPE2, COMM, TSSE, TENC = None, None, None, None, None

# HEADER 1: Untuk API V2 & Download (Browser-like)
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.beatstars.com",
    "Referer": "https://www.beatstars.com/",
    "Connection": "keep-alive"
}

# HEADER 2: Khusus Algolia (Search Engine)
ALGOLIA_HEADERS = BASE_HEADERS.copy()
ALGOLIA_HEADERS.update({
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47",
    "x-algolia-application-id": "NMMGZJQ6QI",
    "content-type": "application/x-www-form-urlencoded"
})

PLACEHOLDER_COVER = "https://www.beatstars.com/assets/img/placeholder-track.png"

# --- HELPER FORMATTING ---

def parse_metadata_rich(data_list, tags_list=None, bpm=None):
    extracted = []
    
    if data_list:
        iterable = data_list.values() if isinstance(data_list, dict) else data_list
        for item in iterable:
            if isinstance(item, str):
                extracted.append(item)
            elif isinstance(item, dict):
                name = item.get('name') or item.get('slug') or item.get('title')
                if name:
                    extracted.append(str(name))
    
    if tags_list:
        if isinstance(tags_list, list):
            for tag in tags_list[:5]: 
                tag_name = ""
                if isinstance(tag, str):
                    tag_name = tag
                elif isinstance(tag, dict):
                    tag_name = tag.get('name', '')
                if tag_name and tag_name not in extracted:
                    extracted.append(tag_name)
        elif isinstance(tags_list, dict):
            for key, val in tags_list.items():
                if len(extracted) >= 10: break 
                if isinstance(val, str) and val not in extracted:
                    extracted.append(val)

    if bpm:
        extracted.append(f"{bpm} BPM")

    return ", ".join(extracted) if extracted else "BeatStars"

def format_date(timestamp):
    try:
        if not timestamp: return ""
        dt_object = datetime.fromtimestamp(int(timestamp))
        return dt_object.strftime("%Y-%m-%d")
    except Exception:
        return str(timestamp)

def clean_cover_url(url):
    if not url: return None
    url = url.replace(r'\/', '/')
    if "://" not in url and "//" in url:
        url = url.replace("//", "/")
    return url

async def resolve_beatstars_redirect(url):
    """
    Mengikuti redirect (Shortlink/Internal) untuk mendapatkan URL Final.
    Contoh: beatstars.com/7BFWiJ -> beatstars.com/username
    """
    try:
        async with aiohttp.ClientSession(headers=BASE_HEADERS) as session:
            async with session.head(url, allow_redirects=True, timeout=10) as resp:
                return str(resp.url)
    except Exception as e:
        LOGGER.warning(f"Gagal resolve redirect: {e}")
        return url

# --- LOCAL COVER DOWNLOADER ---
async def download_local_cover(session, url, folderpath):
    if not url: return PLACEHOLDER_COVER
    filename = "cover.jpg"
    filepath = os.path.join(folderpath, filename)
    try:
        # Gunakan BASE_HEADERS untuk download gambar
        async with session.get(url, headers=BASE_HEADERS, allow_redirects=True, timeout=15) as resp:
            if resp.status == 200:
                content = await resp.read()
                if not content: return PLACEHOLDER_COVER
                with open(filepath, 'wb') as f:
                    f.write(content)
                return filepath
            return PLACEHOLDER_COVER
    except Exception:
        return PLACEHOLDER_COVER

# --- PATCHER METADATA MANUAL ---
def patch_metadata_manual(filepath, album_artist):
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

        if album_artist:
            audio.add(TPE2(encoding=3, text=str(album_artist)))

        audio.save(v2_version=3, v1=2) # Hapus ID3v1
        LOGGER.info("[Patch] Metadata cleaned & fixed.")
    except Exception as e:
        LOGGER.error(f"Gagal patching: {e}")

# --- AUDIO DOWNLOADER ---
async def download_beatstars_file(url, path):
    try:
        folder = os.path.dirname(path)
        if folder: os.makedirs(folder, exist_ok=True)
        async with aiohttp.ClientSession(headers=BASE_HEADERS) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024 * 4)
                            if not chunk: break
                            f.write(chunk)
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        return None
                    return "File kosong."
                return f"HTTP Status: {response.status}"
    except Exception as e:
        return str(e)

# --- MAIN HANDLER ---
async def start_beatstars(link: str, user: dict):
    # 1. RESOLVE REDIRECT TERLEBIH DAHULU
    final_link = await resolve_beatstars_redirect(link)
    if final_link != link:
        LOGGER.info(f"BeatStars Redirect: {link} -> {final_link}")
        link = final_link

    parsed = urlparse(link)
    path = parsed.path.strip("/")
    path_parts = path.split("/")

    # 2. DETEKSI MODE (TRACK / ARTIST)
    if path.startswith("beat/") or "/beat/" in link:
        track_regex = r'(\d+)$'
        track_match = re.search(track_regex, path)
        if track_match:
            track_id = track_match.group(1)
            LOGGER.info(f"BeatStars Track Mode: ID {track_id}")
            await process_single_track(user, track_id)
        else:
            raise Exception("Link Beat tidak valid: ID tidak ditemukan.")
    else:
        if not path_parts or not path_parts[0]:
             raise Exception("Link tidak valid.")
        
        permalink = path_parts[0]
        reserved_words = ['beat', 'tracks', 'feed', 'services', 'publishing', 'dashboard', 'u']
        
        # Handle format /u/username
        if permalink == 'u' and len(path_parts) > 1:
            permalink = path_parts[1]
        
        if permalink.lower() in reserved_words:
             # Jika URL-nya beatstars.com/tracks/..., mungkin tidak valid untuk artis
             raise Exception(f"Link tidak valid: '{permalink}' bukan nama artis.")
             
        LOGGER.info(f"BeatStars Artist Mode: {permalink}")
        await process_artist(user, permalink)

# --- SINGLE TRACK ---
async def process_single_track(user, track_id):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with aiohttp.ClientSession(headers=BASE_HEADERS) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"BeatStars API Error: {resp.status}")
            data = await resp.json()
    
        if not data.get('response', {}).get('data'):
            raise Exception("Track tidak ditemukan.")

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

        filename = f"{artist_name} - {track_title}.mp3"
        filename = re.sub(r'[\\/*?:"<>|]', "", filename)
        filepath = f"{folderpath}/{filename}"

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
            'description': None,
            'comment': None,
            'filepath': filepath,
            'folderpath': folderpath
        }

        stream_url = details.get('stream_url')
        if not stream_url:
            stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

        LOGGER.info(f"Downloading: {track_title}")
        err = await download_beatstars_file(stream_url, filepath)
        if err: raise Exception(f"Gagal download: {err}")

    await set_metadata(meta, user['user_id'])
    patch_metadata_manual(filepath, artist_name)
    await track_upload(meta, user)

# --- ARTIST BATCH ---
async def process_artist(user, permalink):
    # Pastikan permalink lowercase agar API tidak 404 jika user typo kapital
    permalink = permalink.lower()
    
    async with aiohttp.ClientSession(headers=BASE_HEADERS) as session: # Gunakan BASE_HEADERS untuk profile
        artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
        async with session.get(artist_url) as resp:
            if resp.status == 404:
                raise Exception(f"Artis '{permalink}' tidak ditemukan (404).")
            elif resp.status != 200:
                raise Exception(f"API Error: {resp.status}")
            artist_data = await resp.json()
        
        try:
            user_id_num = int(artist_data['response']['data']['profile']['user_id'])
        except:
            raise Exception("Data profil artis tidak valid.")
            
        member_id = f"MR{user_id_num}"
        
        # Gunakan ALGOLIA_HEADERS khusus untuk Algolia
        query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
        
        all_tracks = []
        page = 0
        await user['bot_msg'].edit(f"Mengambil daftar lagu: {permalink}...")
        
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
        if not os.path.exists(folderpath): os.makedirs(folderpath, exist_ok=True)
        
        while True:
            payload = {
                "query": "", "page": page, "hitsPerPage": 1000, "facets": ["*"],
                "facetFilters": [[f"profile.memberId:{member_id}"]],
                "maxValuesPerFacet": 1000
            }
            # Session khusus Algolia atau update header sementara
            async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as algolia_session:
                async with algolia_session.post(query_url, json=payload) as resp:
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
                rich_genre = parse_metadata_rich(hit.get('metadata', {}).get('genres', []), hit.get('metadata', {}).get('tags', []), hit.get('metadata', {}).get('bpm', 0))
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
                    'description': None,
                    'comment': None
                })
            page += 1
            if page >= search_res.get('nbPages', 0): break

    if not all_tracks: raise Exception("Tidak ada track ditemukan.")

    album_meta = {
        'type': 'album', 'title': f"Tracks by {permalink}", 'artist': all_tracks[0]['artist'],
        'albumartist': all_tracks[0]['artist'], 'cover': all_tracks[0]['cover'],
        'provider': 'BeatStars', 'folderpath': folderpath, 'poster_msg': None, 'zip_path': None, 'tracks': []
    }

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    if art_poster: album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    LOGGER.info(f"Ditemukan {len(all_tracks)} track. Memulai unduhan...")
    await user['bot_msg'].edit(f"Ditemukan {len(all_tracks)} track. Memulai unduhan...")

    total_items = len(all_tracks)
    for i, t in enumerate(all_tracks):
        try:
            filename = f"{t['artist']} - {t['title']}.mp3"
            filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            filepath = f"{folderpath}/{filename}"
            
            t['filepath'] = filepath
            t['folderpath'] = folderpath
            t['tracknumber'] = i + 1
            t['totaltracks'] = total_items
            t['type'] = 'track'

            if i % 5 == 0:
                try: await user['bot_msg'].edit(f"Mengunduh {i+1}/{total_items}: {t['title']}")
                except: pass

            err = await download_beatstars_file(t['url'], filepath)
            if err:
                LOGGER.error(f"Gagal: {t['title']} ({err})")
                continue
            
            t['cover'] = await download_local_cover(session, t['cover'], folderpath)
            await set_metadata(t, user['user_id'])
            patch_metadata_manual(filepath, t['albumartist'])
            album_meta['tracks'].append(t)
        except Exception as e:
            LOGGER.error(f"Error track {t['title']}: {e}")

    if not album_meta['tracks']: raise Exception("Gagal mengunduh semua track.")
    if artist_zip or album_zip or playlist_zip:
        await user['bot_msg'].edit("Sedang membuat file Zip...")
        album_meta['zip_path'] = await zip_handler(folderpath)

    await album_upload(album_meta, user)
