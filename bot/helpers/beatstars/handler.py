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

# Headers lengkap
ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", 
    "x-algolia-application-id": "NMMGZJQ6QI",
    "content-type": "application/x-www-form-urlencoded",
    "Origin": "https://www.beatstars.com",
    "Referer": "https://www.beatstars.com/",
    "Connection": "keep-alive"
}

# Gunakan placeholder yang lebih umum/publik jika BeatStars memblokir
PLACEHOLDER_COVER = "https://www.beatstars.com/assets/img/placeholder-track.png"

# --- HELPER FORMATTING ---

def parse_genres(data_list):
    if not data_list:
        return None
    extracted = []
    for item in data_list:
        if isinstance(item, str):
            extracted.append(item)
        elif isinstance(item, dict):
            name = item.get('name') or item.get('slug') or item.get('title')
            if name:
                extracted.append(str(name))
    return ", ".join(extracted) if extracted else None

def format_date(timestamp):
    try:
        if not timestamp:
            return ""
        dt_object = datetime.fromtimestamp(int(timestamp))
        return dt_object.strftime("%Y-%m-%d")
    except Exception:
        return str(timestamp)

def clean_cover_url(url):
    """
    Membersihkan URL Cover.
    Kita tidak lagi memaksa ganti domain karena terbukti 404.
    Kita hanya memperbaiki sintaks URL.
    """
    if not url:
        return PLACEHOLDER_COVER
    
    # 1. Hapus double slash // (kecuali https://)
    if "://" in url:
        protocol, path = url.split("://", 1)
        url = f"{protocol}://{path.replace('//', '/')}"
    else:
        url = url.replace("//", "/")

    # 2. Fix typo ekstensi di URL filter
    url = url.replace("format(.jpeg)", "format(jpeg)")
    
    return url

async def verify_cover_url(session, url):
    """
    Mengecek apakah URL gambar bisa diakses.
    UPDATE: Menerima 200 (OK), 301 (Moved), 302 (Found/Redirect).
    """
    if not url or url == PLACEHOLDER_COVER:
        return PLACEHOLDER_COVER
        
    try:
        # Gunakan allow_redirects=True
        async with session.head(url, allow_redirects=True, timeout=5) as resp:
            if resp.status in [200, 301, 302]:
                return url
            else:
                LOGGER.warning(f"Cover art mati (HTTP {resp.status}): {url}")
                return PLACEHOLDER_COVER
    except Exception as e:
        LOGGER.warning(f"Gagal verifikasi cover: {e}")
        return PLACEHOLDER_COVER

# --- DOWNLOADER ---

async def download_beatstars_file(url, path):
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024 * 4)
                            if not chunk:
                                break
                            f.write(chunk)
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        return None
                    else:
                        return "File kosong atau gagal ditulis."
                else:
                    return f"HTTP Status: {response.status} (URL: {url})"
    except Exception as e:
        return str(e)

async def start_beatstars(link: str, user: dict):
    parsed = urlparse(link)
    path = parsed.path.strip("/")
    path_parts = path.split("/")

    # Mode Deteksi
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
             raise Exception("Link tidak valid: Tidak dapat menemukan username artis.")
        permalink = path_parts[0]
        reserved_words = ['beat', 'tracks', 'feed', 'services', 'publishing', 'dashboard']
        if permalink.lower() in reserved_words:
             raise Exception(f"Link tidak valid: '{permalink}' bukan nama artis.")
        LOGGER.info(f"BeatStars Artist Mode: {permalink}")
        await process_artist(user, permalink)

# --- PROCESS SINGLE TRACK ---
async def process_single_track(user, track_id):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"BeatStars API Error: {resp.status}")
            data = await resp.json()
    
        if not data.get('response', {}).get('data'):
            raise Exception("Track tidak ditemukan.")

        details = data['response']['data']['details']
        
        # 1. Cover Handling
        raw_cover = details.get('artwork', {}).get('original')
        clean_url = clean_cover_url(raw_cover)
        final_cover = await verify_cover_url(session, clean_url)

        # 2. Format Tanggal
        release_date_fmt = format_date(details.get('release_date_time', 0))

        artist_name = details.get('musician', {}).get('display_name')
        track_title = details.get('title')
        
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
        filename = f"{artist_name} - {track_title}.mp3"
        filename = re.sub(r'[\\/*?:"<>|]', "", filename)
        filepath = f"{folderpath}/{filename}"

        meta = {
            'title': track_title,
            'artist': artist_name,
            'albumartist': artist_name,
            'album': 'BeatStars Single',
            'tracknumber': 1,
            'totaltracks': 1,
            'volume': 1,
            'totalvolume': 1,
            'copyright': '',
            'isrc': '',
            'release_date': release_date_fmt,
            'date': release_date_fmt[:4] if release_date_fmt else '',
            'cover': final_cover,
            'provider': 'BeatStars',
            'type': 'track', 
            'itemid': str(details.get('track_id')),
            'genre': parse_genres(details.get('genre', [])),
            'duration': '', 
            'explicit': False,
            'filepath': filepath,
            'folderpath': folderpath
        }

        stream_url = details.get('stream_url')
        if not stream_url:
            stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

        LOGGER.info(f"Downloading Single Track: {track_title}")
        
        err = await download_beatstars_file(stream_url, filepath)
        if err:
            raise Exception(f"Gagal download file: {err}")

    await set_metadata(meta, user['user_id'])
    await track_upload(meta, user)

# --- PROCESS ARTIST ---
async def process_artist(user, permalink):
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
        async with session.get(artist_url) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal mengambil profil artis: {resp.status}")
            artist_data = await resp.json()
        
        try:
            user_id_num = int(artist_data['response']['data']['profile']['user_id'])
        except:
            raise Exception("Profil artis tidak valid.")
            
        member_id = f"MR{user_id_num}"
        query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
        
        all_tracks = []
        page = 0
        
        await user['bot_msg'].edit(f"Mengambil daftar lagu: {permalink}...")
        
        while True:
            payload = {
                "query": "", "page": page, "hitsPerPage": 1000, "facets": ["*"],
                "facetFilters": [[f"profile.memberId:{member_id}"]],
                "maxValuesPerFacet": 1000
            }
            async with session.post(query_url, json=payload) as resp:
                if resp.status != 200: break
                search_res = await resp.json()

            hits = search_res.get('hits', [])
            if not hits: break
            
            for hit in hits:
                track_id = hit.get('v2Id')
                stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
                
                # Cover Processing
                raw_cover = hit.get('artwork', {}).get('sizes', {}).get('original')
                clean_url = clean_cover_url(raw_cover)
                # Untuk artis, kita asumsi URL bersih sudah benar tanpa cek satu2 agar cepat
                
                ts = hit.get('releaseTimestamp') or hit.get('releaseDate') or 0
                date_fmt = format_date(ts)

                all_tracks.append({
                    'title': hit.get('title'),
                    'artist': hit.get('metadata', {}).get('artistName'),
                    'albumartist': hit.get('metadata', {}).get('artistName'), 
                    'album': f"{hit.get('metadata', {}).get('artistName')} - BeatStars",
                    'cover': clean_url,
                    'itemid': str(track_id),
                    'url': stream_url,
                    'genre': parse_genres(hit.get('metadata', {}).get('genres', [])),
                    'copyright': '', 
                    'isrc': '',
                    'volume': 1,
                    'totalvolume': 1,
                    'duration': '',
                    'explicit': False,
                    'release_date': date_fmt,
                    'date': date_fmt[:4] if date_fmt else ''
                })

            page += 1
            if page >= search_res.get('nbPages', 0): break

    if not all_tracks:
        raise Exception("Tidak ada track ditemukan.")

    folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
    
    album_meta = {
        'type': 'album', 
        'title': f"Tracks by {permalink}",
        'artist': all_tracks[0]['artist'],
        'albumartist': all_tracks[0]['artist'],
        'cover': all_tracks[0]['cover'],
        'provider': 'BeatStars',
        'folderpath': folderpath,
        'poster_msg': None,
        'zip_path': None,
        'tracks': []
    }

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if art_poster:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

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
            
            # Verifikasi cover artist (dengan allow redirects)
            t['cover'] = await verify_cover_url(session, t['cover'])

            await set_metadata(t, user['user_id'])
            album_meta['tracks'].append(t)
            
        except Exception as e:
            LOGGER.error(f"Error track {t['title']}: {e}")

    if not album_meta['tracks']:
        raise Exception("Gagal mengunduh semua track.")

    if artist_zip or album_zip or playlist_zip:
        await user['bot_msg'].edit("Sedang membuat file Zip...")
        album_meta['zip_path'] = await zip_handler(folderpath)

    await album_upload(album_meta, user)
