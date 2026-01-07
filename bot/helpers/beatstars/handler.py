# [FILE BARU: bot/helpers/beatstars/handler.py]

import re
import aiohttp
import json
import asyncio
from bot.logger import LOGGER
from bot.helpers.utils import download_file
from bot.helpers.uploder import track_upload, artist_upload
from bot.helpers.metadata import set_metadata

# Headers dari file utils.go (Go)
ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Accept": "*/*",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", # Public Key
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
            # Asumsi link profile: https://www.beatstars.com/username atau permalink
            # Ambil permalink dari URL
            permalink = link.strip("/").split("/")[-1]
            await process_artist(session, permalink, user)

async def process_single_track(session, track_id, user):
    # Porting dari track.go -> getTrack
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with session.get(url) as resp:
        if resp.status != 200:
            raise Exception(f"BeatStars API Error: {resp.status}")
        data = await resp.json()
    
    if not data.get('response', {}).get('data'):
        raise Exception("Track tidak ditemukan atau data kosong.")

    details = data['response']['data']['details']
    
    # Mapping Metadata
    meta = {
        'title': details.get('title'),
        'artist': details.get('musician', {}).get('display_name'),
        'album': 'BeatStars Single',
        'tracknumber': 1,
        'totaltracks': 1,
        'release_date': str(details.get('release_date_time', ''))[:10], # timestamp to YYYY-MM-DD approx logic
        'cover': details.get('artwork', {}).get('original'),
        'provider': 'BeatStars',
        'type': 'track',
        'itemid': str(details.get('track_id')),
        'genre': ", ".join(details.get('genre', [])) if details.get('genre') else None,
        'folderpath': f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
    }

    # Stream URL Logic dari helpers.go/track.go
    stream_url = details.get('stream_url')
    # Fallback construct link jika stream_url kosong di response detail (jarang, tapi jaga-jaga)
    if not stream_url:
        stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

    # Download
    filename = f"{meta['artist']} - {meta['title']}.mp3" # Default mp3
    filepath = f"{meta['folderpath']}/{filename}"
    meta['filepath'] = filepath

    LOGGER.info(f"Downloading BeatStars Track: {meta['title']}")
    
    # Gunakan utils.download_file
    err = await download_file(stream_url, filepath)
    if err:
        raise Exception(f"Gagal download file: {err}")

    # Cek tipe konten sebenarnya (jika utils.download_file tidak handle ekstensi otomatis)
    # Di kode Go ada deteksi content-type, tapi di sini kita asumsikan mp3 dulu,
    # atau biarkan set_metadata mendeteksi via mutagen.

    await set_metadata(meta, user['user_id'])
    await track_upload(meta, user)


async def process_artist(session, permalink, user):
    # Porting dari artist.go -> getArtistTracks
    
    # 1. Dapatkan UserID dari Permalink
    artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
    async with session.get(artist_url) as resp:
        if resp.status != 200:
            raise Exception(f"Gagal mengambil profil artis: {resp.status}")
        artist_data = await resp.json()
    
    try:
        user_id_num = int(artist_data['response']['data']['profile']['user_id'])
    except KeyError:
        raise Exception("Profil artis tidak valid atau User ID tidak ditemukan.")
        
    member_id = f"MR{user_id_num}"
    LOGGER.info(f"BeatStars Artist: {permalink} -> {member_id}")

    # 2. Query Algolia
    # URL Algolia dari artist.go
    query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
    
    all_tracks = []
    page = 0
    
    while True:
        # Payload JSON persis seperti di artist.go
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
            # Construct Stream URL
            stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
            
            meta_track = {
                'title': hit.get('title'),
                'artist': hit.get('metadata', {}).get('artistName'),
                'album': f"{hit.get('metadata', {}).get('artistName')} - BeatStars",
                'cover': hit.get('artwork', {}).get('sizes', {}).get('original'),
                'itemid': str(track_id),
                'url': stream_url, # Simpan URL stream langsung
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
    # Kita siapkan struktur untuk artist_upload
    folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
    
    downloaded_tracks = []
    
    # Download loop (bisa dibuat concurrent dengan run_concurrent_tasks jika mau)
    for i, t in enumerate(all_tracks):
        try:
            filename = f"{t['artist']} - {t['title']}.mp3"
            filepath = f"{folderpath}/{filename}"
            t['filepath'] = filepath
            t['folderpath'] = folderpath
            t['provider'] = 'BeatStars'
            t['tracknumber'] = i + 1
            t['totaltracks'] = len(all_tracks)
            t['type'] = 'track' # individual type

            # Download
            err = await download_file(t['url'], filepath)
            if err:
                LOGGER.error(f"Gagal download {t['title']}: {err}")
                continue
                
            await set_metadata(t, user['user_id'])
            downloaded_tracks.append(t)
            
        except Exception as e:
            LOGGER.error(f"Error processing track {t['title']}: {e}")

    if not downloaded_tracks:
        raise Exception("Gagal mengunduh semua track.")

    # Kemas dalam struktur Album/Artist untuk uploader
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
