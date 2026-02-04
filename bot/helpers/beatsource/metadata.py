# [GANTI SELURUH FILE: bot/helpers/beatsource/metadata.py]

import copy
import re
import aiohttp
import urllib.parse
import logging
import os 
import traceback 
import asyncio
import random
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .api import BeatsourceAPI, BeatsourceError
from bot.logger import LOGGER
from .manager import beatsource_manager

FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

# --- REGEX URL ---
BEATSOURCE_URL_REGEX = re.compile(
    r"https?://(?:www\.)?beatsource\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlist|playlists|chart).*/(?P<id>\d+)[^/]*?(?:$|\?)"
)

def custom_url_parse(url: str):
    """Mem-parse URL Beatsource."""
    match = BEATSOURCE_URL_REGEX.search(url)
    if not match: raise ValueError(f"URL Invalid: {url}")
    t, i = match.group("type"), match.group("id")
    if t == "release": t = "album"
    elif t in ["playlists", "chart"]: 
        return "playlist", i, {"is_chart": t == "chart"}
    return t, i, {}

async def _generate_artwork_url(dynamic_uri: str, size: int = 1400):
    if not dynamic_uri: return None
    res_pattern = re.compile(r"\d{3,4}x\d{3,4}")
    if re.search(res_pattern, dynamic_uri):
        dynamic_uri = re.sub(res_pattern, "{w}x{h}", dynamic_uri)
    return dynamic_uri.format(w=size, h=size)

async def _process_cover(metadata: dict, img_url: str):
    final = img_url
    if not final and os.path.exists(FALLBACK_IMAGE_PATH): final = FALLBACK_IMAGE_PATH
    return await create_cover_file(final, metadata)

# --- PROSES METADATA INTI (FIXED) ---

async def process_track_metadata(item_id: str, r_id: str, user: dict, 
                               fetch_stream: bool = True, 
                               pre_data: dict = None, 
                               album_pre_data: dict = None):
    
    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['itemid'] = item_id
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}"

    user_id = user.get('user_id')
    active_client = beatsource_manager.get_client(user_id)
    if not active_client: raise BeatsourceError("No Active Client")

    # 1. Fetch Track Data (Retry Logic)
    track_data = pre_data
    if not track_data:
        for _ in range(2):
            try:
                track_data = await active_client.get_track(item_id)
                if track_data: break
            except: await asyncio.sleep(0.5)
        
    if not track_data: raise BeatsourceError("Track not found.")

    # 2. Fetch Album Data
    release_data = album_pre_data
    if not release_data:
        rid = track_data.get('release', {}).get('id')
        if rid: release_data = await active_client.get_release(rid)
    
    if not release_data: release_data = {}

    # 3. Fill Metadata
    meta['title'] = track_data.get('name')
    if track_data.get('mix_name'): meta['title'] += f" ({track_data['mix_name']})"
    
    meta['artist'] = ", ".join([a['name'] for a in track_data.get("artists", [])])
    meta['album'] = release_data.get('name')
    meta['albumartist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    # [FIX] Date & Explicit
    meta['date'] = release_data.get('publish_date', '')[:10]
    meta['year'] = meta['date'][:4]
    meta['explicit'] = track_data.get('explicit', False)
    meta['duration'] = track_data.get('length_ms', 0) // 1000

    # Track Number Default (Overridden in Album loop)
    meta['tracknumber'] = str(track_data.get('track_number', 1)).zfill(2)
    meta['totaltracks'] = str(release_data.get('track_count', 1))
    
    # Cover
    img = release_data.get('image', {}).get('dynamic_uri') or track_data.get('image', {}).get('dynamic_uri')
    if img:
        img_url = await _generate_artwork_url(img)
        meta['cover'] = await _process_cover(meta, img_url)
        meta['thumbnail'] = await create_cover_file(await _generate_artwork_url(img, 400), meta, thumbnail=True)

    # 4. Stream & Quality Logic
    user_qual = beatsource_manager.get_user_quality(user_id)
    
    # [FIX] Set placeholder quality agar tidak kosong di caption saat fetch_stream=False
    meta['quality'] = user_qual.capitalize()
    meta['extension'] = 'flac' if user_qual == 'lossless' else 'm4a'
    
    if fetch_stream:
        # Priority: Lossless -> High -> Medium
        qualities = ["medium"]
        if user_qual == "lossless": qualities = ["lossless", "high", "medium"]
        elif user_qual == "high": qualities = ["high", "medium"]
        
        dl_url = None
        for q in qualities:
            try:
                await asyncio.sleep(random.uniform(0.1, 0.3))
                d = await active_client.get_track_download(item_id, q)
                if d.get('location'):
                    dl_url = d['location']
                    meta['quality'] = q.capitalize()
                    meta['extension'] = 'flac' if q == 'lossless' else 'm4a'
                    break
            except: continue
            
        if not dl_url: raise BeatsourceError("Gagal mengambil link download.")
        meta['download_url'] = dl_url
    else:
        meta['download_url'] = None

    return meta

async def process_album_metadata(item_id: str, r_id: str, user: dict):
    user_id = user.get('user_id')
    active_client = beatsource_manager.get_client(user_id)
    if not active_client: raise BeatsourceError("No Client")

    # 1. Fetch Album
    release_data = await active_client.get_release(item_id)
    if not release_data: raise BeatsourceError("Album not found.")
    
    # 2. Fetch Tracks (Pagination)
    tracks = []
    page = 1
    while True:
        try:
            res = await active_client.get_release_tracks(item_id, page=page)
            if not res.get('results'): break
            tracks.extend(res['results'])
            if not res.get('next'): break
            page += 1
            await asyncio.sleep(0.5)
        except: break

    # 3. Setup Metadata Album
    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'
    meta['title'] = release_data['name']
    meta['artist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    # [FIX] ISI METADATA PENTING YANG HILANG
    meta['date'] = release_data.get('publish_date', '')[:10]
    meta['year'] = meta['date'][:4]
    meta['totaltracks'] = str(len(tracks))
    meta['totalvolume'] = "1"
    
    # Set Quality Placeholder
    pref_qual = beatsource_manager.get_user_quality(user_id)
    meta['quality'] = pref_qual.capitalize()
    
    # Cover
    img = release_data.get('image', {}).get('dynamic_uri')
    if img:
        img_url = await _generate_artwork_url(img)
        meta['cover'] = await _process_cover(meta, img_url)
        meta['thumbnail'] = await create_cover_file(await _generate_artwork_url(img, 400), meta, thumbnail=True)

    meta['tracks'] = []
    album_explicit = False

    # 4. Loop Tracks dengan Forced Numbering
    for i, t in enumerate(tracks):
        try:
            # Pass release_data agar tidak fetch ulang
            tm = await process_track_metadata(str(t['id']), r_id, user, 
                                            fetch_stream=False, 
                                            pre_data=t, 
                                            album_pre_data=release_data)
            
            # [FIX] PAKSA NOMOR TRACK (01, 02, ...)
            tm['tracknumber'] = str(i + 1).zfill(2)
            tm['totaltracks'] = meta['totaltracks']
            
            # Wariskan Cover Album
            tm['cover'] = meta['cover']
            
            if tm.get('explicit'): album_explicit = True
                
            meta['tracks'].append(tm)
        except Exception as e:
            LOGGER.error(f"Error track {t.get('id')}: {e}")

    meta['explicit'] = album_explicit
    if not meta['tracks']: raise BeatsourceError("Album kosong.")
    
    return meta

async def process_playlist_metadata(item_id: str, r_id: str, user: dict, extra: dict):
    user_id = user.get('user_id')
    active_client = beatsource_manager.get_client(user_id)
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

    # 3. Setup Metadata
    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}_PLAY"
    meta['type'] = 'playlist'
    meta['title'] = pl_data['name']
    meta['artist'] = "Beatsource Chart" if is_chart else pl_data.get('user', {}).get('name', 'User')
    
    # [FIX] Isi Metadata Playlist
    meta['totaltracks'] = str(len(tracks))
    pref_qual = beatsource_manager.get_user_quality(user_id)
    meta['quality'] = pref_qual.capitalize()

    img = pl_data.get('image', {}).get('dynamic_uri')
    if not img and pl_data.get('release_images'):
        img = pl_data['release_images'][0].get('dynamic_uri')
    if img:
        img_url = await _generate_artwork_url(img)
        meta['cover'] = await _process_cover(meta, img_url)

    meta['tracks'] = []
    album_cache = {}
    
    for i, item in enumerate(tracks):
        try:
            t_data = item if is_chart else item.get('track')
            if not t_data: continue
            
            # Cache album kecil-kecilan
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
            
            # [FIX] Numbering
            tm['tracknumber'] = str(i + 1).zfill(2)
            meta['tracks'].append(tm)
        except: continue

    return meta
