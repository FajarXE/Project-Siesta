# [GANTI FILE: bot/helpers/beatstars/handler.py]

import re
import aiohttp
import asyncio
from urllib.parse import urlparse
from bot.logger import LOGGER
from bot.helpers.utils import download_file
from bot.helpers.uploder import track_upload, artist_upload
from bot.helpers.metadata import set_metadata

# Headers dari file utils.go (Go) - Menggunakan Public API Key
ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "*/*",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", 
    "x-algolia-application-id": "NMMGZJQ6QI",
    "content-type": "application/x-www-form-urlencoded",
    "Origin": "https://www.beatstars.com",
    "Referer": "https://www.beatstars.com/"
}

async def start_beatstars(link: str, user: dict):
    # Regex untuk Track: /beat/judul-lagu-12345
    track_regex = r'/beat/.*?-(\d+)$'
    track_match = re.search(track_regex, link)

    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        if track_match:
            # --- SINGLE TRACK DOWNLOAD ---
            track_id = track_match.group(1)
            await process_single_track(session, track_id, user)
        else:
            # --- ARTIST DOWNLOAD ---
            # PERBAIKAN LOGIKA EKSTRAKSI PERMALINK
            # Menggunakan urlparse untuk menangani link seperti:
            # https://www.beatstars.com/username/tracks
            # https://www.beatstars.com/username/feed
            
            parsed = urlparse(link)
            # Hapus slash awal/akhir dan split
            path_parts = parsed.path.strip("/").split("/")
            
            # Ambil bagian pertama path sebagai username (permalink)
            if not path_parts or not path_parts[0]:
                raise Exception("Link tidak valid: Tidak dapat menemukan username artis.")
            
            permalink = path_parts[0]
            
            LOGGER.info(f"BeatStars: Mendeteksi permalink artis: {permalink}")
            await process_artist(session, permalink, user)

async def process_single_track(session, track_id, user):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with session.get(url) as resp:
        if resp.status != 200:
            raise Exception(f"BeatStars API Error (Track): {resp.status}")
        data = await resp.json()
    
    if not data.get('response', {}).get('data'):
        raise Exception("Track tidak ditemukan atau data kosong.")

    details = data['response']['data']['details']
    
    meta = {
        'title': details.get('title'),
        'artist': details.get('musician', {}).get('display_name'),
        'album': 'BeatStars Single',
        'tracknumber': 1,
        'totaltracks': 1,
        'release_date': str(details.get('release_date_time', ''))[:10],
        'cover': details.get('artwork', {}).get('original'),
        'provider': 'BeatStars',
        'type': 'track',
        'itemid': str(details.get('track_id')),
        'genre': ", ".join(details.get('genre', [])) if details.get('genre') else None,
        'folderpath': f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
    }

    stream_url = details.get('stream_url')
    if not stream_url:
        stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

    filename = f"{meta['artist']} - {meta['title']}.mp3"
    filepath = f"{meta['folderpath']}/{filename}"
    meta['filepath'] = filepath

    LOGGER.info(f"Downloading BeatStars Track: {meta['title']}")
    
    err = await download_file(stream_url, filepath)
    if err:
        raise Exception(f"Gagal download file: {err}")

    await set_metadata(meta, user['user_id'])
    await track_upload(meta, user)


async def process_artist(session, permalink, user):
    # 1. Dapatkan UserID dari Permalink
    artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
    
    async with session.get(artist_url) as resp:
        if resp.status == 404:
            raise Exception(f"Artis '{permalink}' tidak ditemukan (404). Periksa kembali link Anda.")
        elif resp.status != 200:
            raise Exception(f"Gagal mengambil profil artis: {resp.status}")
        
        artist_data = await resp.json()
    
    try:
        user_id_num = int(artist_data['response']['data']['profile']['user_id'])
    except (KeyError, TypeError):
        raise Exception("Profil artis tidak valid atau User ID tidak ditemukan dalam respons API.")
        
    member_id = f"MR{user_id_num}"
    LOGGER.info(f"BeatStars Artist: {permalink} -> {member_id}")

    # 2. Query Algolia
    query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
    
    all_tracks = []
    page = 0
    
    await user['bot_msg'].edit(f"Mengambil daftar lagu dari artis: {permalink}...")
    
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
                LOGGER.warning(f"Algolia Query Error: {resp.status}")
                break
            search_res = await resp.json()

        hits = search_res.get('hits', [])
        nb_pages = search_res.get('nbPages', 0)
        
        for hit in hits:
            track_id = hit.get('v2Id')
            stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
            
            meta_track = {
                'title': hit.get('title'),
                'artist': hit.get('metadata', {}).get('artistName'),
                'album': f"{hit.get('metadata', {}).get('artistName')} - BeatStars",
                'cover': hit.get('artwork', {}).get('sizes', {}).get('original'),
                'itemid': str(track_id),
                'url': stream_url,
                'genre': ", ".join(hit.get('metadata', {}).get('genres', [])) if hit.get('metadata', {}).get('genres') else None
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
    
    # Batasi unduhan maksimal agar tidak spam/ban (opsional, saat ini tidak dibatasi)
    total_items = len(all_tracks)

    for i, t in enumerate(all_tracks):
        try:
            filename = f"{t['artist']} - {t['title']}.mp3"
            # Bersihkan nama file dari karakter ilegal
            filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            
            filepath = f"{folderpath}/{filename}"
            t['filepath'] = filepath
            t['folderpath'] = folderpath
            t['provider'] = 'BeatStars'
            t['tracknumber'] = i + 1
            t['totaltracks'] = total_items
            t['type'] = 'track'

            # Update status berkala setiap 5 lagu
            if i % 5 == 0:
                try:
                    await user['bot_msg'].edit(f"Mengunduh {i+1}/{total_items}: {t['title']}")
                except: pass

            err = await download_file(t['url'], filepath)
            if err:
                LOGGER.error(f"Gagal download {t['title']}: {err}")
                continue
                
            await set_metadata(t, user['user_id'])
            downloaded_tracks.append(t)
            
        except Exception as e:
            LOGGER.error(f"Error processing track {t['title']}: {e}")

    if not downloaded_tracks:
        raise Exception("Gagal mengunduh semua track (koneksi atau limit).")

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
