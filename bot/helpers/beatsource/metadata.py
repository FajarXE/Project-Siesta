# [GANTI SELURUH FILE: bot/helpers/beatsource/metadata.py]

import copy
import re
import asyncio
from bot.logger import LOGGER
from .api import BeatsourceAPI, BeatsourceError
from .manager import beatsource_manager
from ..metadata import metadata as base_meta, create_cover_file

BEATSOURCE_URL_REGEX = re.compile(
    r"https?://(?:www\.)?beatsource\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlist|playlists|chart).*/(?P<id>\d+)[^/]*?(?:$|\?)"
)

def custom_url_parse(url: str):
    match = BEATSOURCE_URL_REGEX.search(url)
    if not match: raise ValueError(f"URL Invalid: {url}")
    t, i = match.group("type"), match.group("id")
    if t == "release": t = "album"
    elif t in ["playlists", "chart"]: 
        return "playlist", i, {"is_chart": t == "chart"}
    return t, i, {}

# --- CORE METADATA ---

async def process_track_metadata(item_id: str, r_id: str, user: dict, 
                               fetch_stream: bool = True, 
                               pre_data: dict = None, 
                               album_pre_data: dict = None):
    """
    [FIX] Menerima pre_data (data track) dan album_pre_data (data album)
    untuk menghindari request API berulang.
    """
    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}"

    user_id = user.get('user_id')
    active_client = beatsource_manager.get_client(user_id)
    if not active_client: raise BeatsourceError("No Active Client")

    # 1. Gunakan data cache jika ada
    track_data = pre_data
    if not track_data:
        track_data = await active_client.get_track(item_id)
        
    # 2. Ambil data album (gunakan cache jika ada)
    # [CRITICAL FIX] Ini mencegah 20x request get_release untuk album isi 20 lagu
    release_data = album_pre_data
    if not release_data:
        rid = track_data.get('release', {}).get('id')
        if rid: release_data = await active_client.get_release(rid)
    
    if not track_data or not release_data:
        raise BeatsourceError("Metadata tidak lengkap.")

    # 3. Parsing Metadata
    meta['title'] = track_data.get('name')
    if track_data.get('mix_name'): meta['title'] += f" ({track_data['mix_name']})"
    
    meta['artist'] = ", ".join([a['name'] for a in track_data.get("artists", [])])
    meta['album'] = release_data.get('name')
    meta['albumartist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    meta['tracknumber'] = str(track_data.get('track_number', 1)).zfill(2)
    meta['totaltracks'] = str(release_data.get('track_count', 1))
    meta['date'] = release_data.get('publish_date', '')[:10]
    meta['year'] = meta['date'][:4]
    meta['duration'] = track_data.get('length_ms', 0) // 1000
    
    # Cover
    img = release_data.get('image', {}).get('dynamic_uri') or track_data.get('image', {}).get('dynamic_uri')
    if img:
        meta['cover'] = await create_cover_file(img.format(w=1400, h=1400), meta)
        meta['thumbnail'] = await create_cover_file(img.format(w=400, h=400), meta, thumbnail=True)

    # 4. Stream Logic
    user_qual = beatsource_manager.get_user_quality(user_id)
    meta['quality'] = user_qual.capitalize()
    
    if fetch_stream:
        # Tentukan urutan kualitas
        qualities = ["medium"]
        if user_qual == "lossless": qualities = ["lossless", "high", "medium"]
        elif user_qual == "high": qualities = ["high", "medium"]
        
        dl_url = None
        for q in qualities:
            try:
                # Delay random kecil
                await asyncio.sleep(random.uniform(0.1, 0.3))
                d = await active_client.get_track_download(item_id, q)
                if d.get('location'):
                    dl_url = d['location']
                    meta['quality'] = q.capitalize()
                    meta['extension'] = 'flac' if q == 'lossless' else 'm4a'
                    break
            except: continue
            
        if not dl_url: raise BeatsourceError("Gagal mengambil link download (Cek Langganan/Region).")
        meta['download_url'] = dl_url
    else:
        # Placeholder untuk playlist/album
        meta['download_url'] = None
        meta['extension'] = 'flac' if user_qual == 'lossless' else 'm4a'

    return meta

async def process_album_metadata(item_id: str, r_id: str, user: dict):
    active_client = beatsource_manager.get_client(user.get('user_id'))
    if not active_client: raise BeatsourceError("No Client")

    # 1. Fetch Album Sekali Saja
    release_data = await active_client.get_release(item_id)
    
    # 2. Fetch Tracks
    tracks = []
    page = 1
    while True:
        try:
            res = await active_client.get_release_tracks(item_id, page=page)
            if not res.get('results'): break
            tracks.extend(res['results'])
            if not res.get('next'): break
            page += 1
            await asyncio.sleep(0.5) # Delay paginasi
        except: break

    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'
    meta['title'] = release_data['name']
    meta['artist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    img = release_data.get('image', {}).get('dynamic_uri')
    if img:
        meta['cover'] = await create_cover_file(img.format(w=1400, h=1400), meta)
        meta['thumbnail'] = meta['cover']

    meta['tracks'] = []
    for t in tracks:
        try:
            # [CRITICAL] PASS release_data ke sini!
            tm = await process_track_metadata(str(t['id']), r_id, user, 
                                            fetch_stream=False, 
                                            pre_data=t, 
                                            album_pre_data=release_data)
            tm['cover'] = meta['cover']
            meta['tracks'].append(tm)
        except Exception as e:
            LOGGER.error(f"Error track {t.get('id')}: {e}")

    if not meta['tracks']: raise BeatsourceError("Album kosong.")
    return meta

async def process_playlist_metadata(item_id: str, r_id: str, user: dict, extra: dict):
    active_client = beatsource_manager.get_client(user.get('user_id'))
    is_chart = extra.get('is_chart', False)
    
    # 1. Fetch Info
    if is_chart: pl_data = await active_client.get_chart(item_id)
    else: pl_data = await active_client.get_playlist(item_id)
    
    # 2. Fetch Tracks
    tracks = []
    page = 1
    endpoint = active_client.get_chart_tracks if is_chart else active_client.get_playlist_tracks
    while True:
        try:
            res = await endpoint(item_id, page=page)
            if not res.get('results'): break
            tracks.extend(res['results'])
            if len(tracks) >= res.get('count', 0) or len(tracks) >= 2000: break
            page += 1
            await asyncio.sleep(0.5)
        except: break

    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}_PLAY"
    meta['type'] = 'playlist'
    meta['title'] = pl_data['name']
    meta['artist'] = "Beatsource Chart" if is_chart else pl_data.get('user', {}).get('name', 'User')

    img = pl_data.get('image', {}).get('dynamic_uri')
    if not img and pl_data.get('release_images'):
        img = pl_data['release_images'][0].get('dynamic_uri')
    if img:
        meta['cover'] = await create_cover_file(img.format(w=1400, h=1400), meta)

    meta['tracks'] = []
    
    # Cache album kecil-kecilan
    album_cache = {}
    
    for item in tracks:
        try:
            t_data = item if is_chart else item.get('track')
            if not t_data: continue
            
            # Cek cache album
            rid = t_data.get('release', {}).get('id')
            rel_data = None
            if rid:
                if rid in album_cache: rel_data = album_cache[rid]
                else:
                    try:
                        rel_data = await active_client.get_release(rid)
                        album_cache[rid] = rel_data
                        await asyncio.sleep(0.2)
                    except: pass
            
            tm = await process_track_metadata(str(t_data['id']), r_id, user,
                                            fetch_stream=False,
                                            pre_data=t_data,
                                            album_pre_data=rel_data)
            meta['tracks'].append(tm)
        except: continue

    return meta
