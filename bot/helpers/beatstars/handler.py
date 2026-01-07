# [GANTI FILE: bot/helpers/beatstars/handler.py]

import os
import re
import aiohttp
import asyncio
from urllib.parse import urlparse
from bot.logger import LOGGER
from bot.helpers.uploder import track_upload, artist_upload
from bot.helpers.metadata import set_metadata

# Headers lengkap untuk menghindari 403 Forbidden
ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "*/*",
    "Accept-Language": "en-CA,en-US;q=0.7,en;q=0.3",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", 
    "x-algolia-application-id": "NMMGZJQ6QI",
    "content-type": "application/x-www-form-urlencoded",
    "Origin": "https://www.beatstars.com",
    "Connection": "keep-alive",
    "Referer": "https://www.beatstars.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-GPC": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache"
}

# --- FUNGSI HELPER PARSING GENRE ---
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
                
    if not extracted:
        return None
        
    return ", ".join(extracted)

# --- FUNGSI DOWNLOADER KHUSUS (MENGHINDARI 403 & MEMBUAT FOLDER) ---
async def download_beatstars_file(url, path):
    """
    Downloader lokal yang menyertakan headers ALGOLIA_HEADERS.
    Otomatis membuat folder tujuan jika belum ada.
    """
    try:
        # 1. Pastikan folder tujuan ada
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        # 2. Lakukan request download
        async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
            async with session.get(url) as response:
                if response.status == 200:
                    with open(path, 'wb') as f:
                        while True:
                            chunk = await response.content.read(1024 * 4)
                            if not chunk:
                                break
                            f.write(chunk)
                    
                    # Verifikasi file ada dan tidak kosong
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

    # KASUS 1: TRACK (Link mengandung /beat/)
    if path.startswith("beat/") or "/beat/" in link:
        track_regex = r'(\d+)$'
        track_match = re.search(track_regex, path)
        
        if track_match:
            track_id = track_match.group(1)
            LOGGER.info(f"BeatStars Track Mode: ID {track_id}")
            await process_single_track(user, track_id)
        else:
            raise Exception("Link Beat tidak valid: Tidak dapat menemukan ID Lagu di akhir URL.")

    # KASUS 2: ARTIST (Link profil biasa)
    else:
        if not path_parts or not path_parts[0]:
             raise Exception("Link tidak valid: Tidak dapat menemukan username artis.")
        
        permalink = path_parts[0]
        
        reserved_words = ['beat', 'tracks', 'feed', 'services', 'publishing', 'dashboard']
        if permalink.lower() in reserved_words:
             raise Exception(f"Link tidak valid: '{permalink}' bukan nama artis.")

        LOGGER.info(f"BeatStars Artist Mode: {permalink}")
        await process_artist(user, permalink)


async def process_single_track(user, track_id):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"BeatStars API Error (Track): {resp.status}")
            data = await resp.json()
    
    if not data.get('response', {}).get('data'):
        raise Exception("Track tidak ditemukan atau data kosong.")

    details = data['response']['data']['details']
    
    cover_url = details.get('artwork', {}).get('original')
    if not cover_url:
        cover_url = "https://www.beatstars.com/assets/img/placeholder-track.png"

    meta = {
        'title': details.get('title'),
        'artist': details.get('musician', {}).get('display_name'),
        'album': 'BeatStars Single',
        'tracknumber': 1,
        'totaltracks': 1,
        'release_date': str(details.get('release_date_time', ''))[:10],
        'cover': cover_url,
        'provider': 'BeatStars',
        'type': 'track',
        'itemid': str(details.get('track_id')),
        'genre': parse_genres(details.get('genre', [])),
        'duration': '', # <-- DITAMBAHKAN: Agar set_metadata auto-calc
        'folderpath': f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
    }

    stream_url = details.get('stream_url')
    if not stream_url:
        stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

    filename = f"{meta['artist']} - {meta['title']}.mp3"
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    
    filepath = f"{meta['folderpath']}/{filename}"
    meta['filepath'] = filepath

    LOGGER.info(f"Downloading BeatStars Track: {meta['title']}")
    
    err = await download_beatstars_file(stream_url, filepath)
    if err:
        raise Exception(f"Gagal download file: {err}")

    await set_metadata(meta, user['user_id'])
    await track_upload(meta, user)


async def process_artist(user, permalink):
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        # 1. Dapatkan UserID
        artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
        async with session.get(artist_url) as resp:
            if resp.status == 404:
                raise Exception(f"Artis '{permalink}' tidak ditemukan (404).")
            elif resp.status != 200:
                raise Exception(f"Gagal mengambil profil artis: {resp.status}")
            
            artist_data = await resp.json()
        
        try:
            user_id_num = int(artist_data['response']['data']['profile']['user_id'])
        except (KeyError, TypeError):
            raise Exception("Profil artis tidak valid atau User ID tidak ditemukan.")
            
        member_id = f"MR{user_id_num}"
        
        # 2. Query Algolia
        query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
        
        all_tracks = []
        page = 0
        
        await user['bot_msg'].edit(f"Mengambil daftar lagu artis: {permalink}...")
        
        while True:
            payload = {
                "query": "",
                "page": page,
                "hitsPerPage": 1000,
                "facets": ["*"],
                "analytics": False,
                "tagFilters": [],
                "facetFilters": [[f"profile.memberId:{member_id}"]],
                "maxValuesPerFacet": 1000,
                "enableABTest": False,
                "userToken": None,
                "filters": "",
                "ruleContexts": []
            }

            async with session.post(query_url, json=payload) as resp:
                if resp.status != 200:
                    break
                search_res = await resp.json()

            hits = search_res.get('hits', [])
            nb_pages = search_res.get('nbPages', 0)
            
            for hit in hits:
                track_id = hit.get('v2Id')
                stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
                
                cover_hit = hit.get('artwork', {}).get('sizes', {}).get('original')
                if not cover_hit:
                    cover_hit = "https://www.beatstars.com/assets/img/placeholder-track.png"

                raw_genres = hit.get('metadata', {}).get('genres', [])

                meta_track = {
                    'title': hit.get('title'),
                    'artist': hit.get('metadata', {}).get('artistName'),
                    'album': f"{hit.get('metadata', {}).get('artistName')} - BeatStars",
                    'cover': cover_hit,
                    'itemid': str(track_id),
                    'url': stream_url,
                    'genre': parse_genres(raw_genres),
                    'duration': '' # <-- DITAMBAHKAN
                }
                all_tracks.append(meta_track)

            page += 1
            if page >= nb_pages:
                break

    if not all_tracks:
        raise Exception("Tidak ada track ditemukan untuk artis ini.")

    LOGGER.info(f"Ditemukan {len(all_tracks)} track untuk {permalink}")
    await user['bot_msg'].edit(f"Ditemukan {len(all_tracks)} track. Memulai unduhan...")

    # 3. Proses Batch Download
    folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
    downloaded_tracks = []
    total_items = len(all_tracks)

    for i, t in enumerate(all_tracks):
        try:
            filename = f"{t['artist']} - {t['title']}.mp3"
            filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            
            filepath = f"{folderpath}/{filename}"
            t['filepath'] = filepath
            t['folderpath'] = folderpath
            t['provider'] = 'BeatStars'
            t['tracknumber'] = i + 1
            t['totaltracks'] = total_items
            t['type'] = 'track'

            if i % 5 == 0:
                try:
                    await user['bot_msg'].edit(f"Mengunduh {i+1}/{total_items}: {t['title']}")
                except: pass

            err = await download_beatstars_file(t['url'], filepath)
            if err:
                LOGGER.error(f"Gagal download {t['title']}: {err}")
                continue
                
            await set_metadata(t, user['user_id'])
            downloaded_tracks.append(t)
            
        except Exception as e:
            LOGGER.error(f"Error processing track {t['title']}: {e}")

    if not downloaded_tracks:
        raise Exception("Gagal mengunduh semua track.")

    final_meta = {
        'type': 'artist',
        'artist': downloaded_tracks[0]['artist'],
        'provider': 'BeatStars',
        'title': f"Tracks by {permalink}",
        'cover': downloaded_tracks[0]['cover'],
        'folderpath': folderpath,
        'albums': [
            {
                'title': 'BeatStars Collection',
                'tracks': downloaded_tracks
            }
        ]
    }

    await artist_upload(final_meta, user)
