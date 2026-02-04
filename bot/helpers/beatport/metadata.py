# [GANTI SELURUH FILE: bot/helpers/beatport/metadata.py]

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
from .api import BeatportAPI, BeatportError
from bot.logger import LOGGER
from .manager import beatport_manager

FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

QUALITY_MAP = {
    "lossless": "lossless",
    "high": "high",
    "medium": "medium"
}

def truncate_artist_list(artist_str: str, max_len: int = 200) -> str: 
    if len(artist_str) > max_len: return artist_str[:max_len] + "..."
    return artist_str

async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    return None 

# [FIX] Fungsi ini dikembalikan karena dibutuhkan handler.py
def custom_url_parse(link: str):
    match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/.+?/(?P<id>\d+)", link)
    if not match: match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/(?P<id>\d+)", link)
    if not match: raise BeatportError(f"URL tidak valid: {link}")
    
    m_type = match.group("type")
    if m_type == "release": m_type = "album"
    elif m_type in ["playlists", "chart"]: m_type = "playlist"
    
    return m_type, match.group("id"), {"is_chart": match.group("type") == "chart"}

async def _generate_artwork_url(dynamic_uri: str, size: int = 1400):
    if not dynamic_uri: return None
    res_pattern = re.compile(r"\d{3,4}x\d{3,4}")
    if re.search(res_pattern, dynamic_uri):
        dynamic_uri = re.sub(res_pattern, "{w}x{h}", dynamic_uri)
    return dynamic_uri.format(w=size, h=size)

async def _process_cover(metadata: dict, beatport_url: str):
    final = beatport_url
    if not final and os.path.exists(FALLBACK_IMAGE_PATH): final = FALLBACK_IMAGE_PATH
    return await create_cover_file(final, metadata)

# --- PROSES METADATA INTI (FIXED) ---

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, fetch_stream: bool = True, album_pre_data: dict = None):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    if not active_client: raise BeatportError("Tidak ada akun Beatport.")
    
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # 1. Get Track Data
    track_data = pre_data
    if not track_data:
        for _ in range(2):
            try:
                track_data = await active_client.get_track(track_id)
                if track_data: break
            except: 
                await asyncio.sleep(1)
    
    if not track_data: raise BeatportError(f"Track {track_id} not found.")

    # 2. Get Album Data
    album_data = album_pre_data 
    if not album_data:
        try:
            rel_id = track_data.get("release", {}).get("id")
            if rel_id:
                album_data = await active_client.get_release(rel_id)
        except: pass
    
    if not album_data: album_data = {} 

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get("name")
    if track_data.get("mix_name"): metadata['title'] += f" ({track_data.get('mix_name')})"
    
    artist_raw = ", ".join([a.get("name") for a in track_data.get("artists", [])])
    albumartist_raw = ", ".join([a.get("name") for a in album_data.get("artists", [])])
    metadata['artist'] = truncate_artist_list(artist_raw)
    metadata['albumartist'] = truncate_artist_list(albumartist_raw)
    
    metadata['album'] = album_data.get("name", "Unknown Album")
    
    # [FIX] Tanggal & Explicit
    metadata['date'] = track_data.get("publish_date", "")[:10]
    metadata['year'] = metadata['date'][:4]
    metadata['explicit'] = track_data.get("explicit", False)
    
    # Track Number Default (Akan di-override oleh Album Loop)
    metadata['tracknumber'] = str(track_data.get("number", 1)).zfill(2)
    metadata['totaltracks'] = str(album_data.get("track_count", 1))
    
    # Cover Logic
    bp_cover = None
    if track_data.get("release", {}).get("image", {}).get("dynamic_uri"):
        bp_cover = await _generate_artwork_url(track_data.get("release").get("image").get("dynamic_uri"))
    elif album_data.get("image", {}).get("dynamic_uri"):
        bp_cover = await _generate_artwork_url(album_data.get("image").get("dynamic_uri"))
    
    metadata['cover'] = await _process_cover(metadata, bp_cover)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover, 80), metadata, True)

    # 3. Stream & Quality Logic
    pref_qual = beatport_manager.get_user_quality(user_id)
    metadata['quality'] = pref_qual.capitalize()
    metadata['extension'] = "flac" if pref_qual == "lossless" else "m4a"

    if fetch_stream:
        qual_order = ["lossless", "high", "medium"] if pref_qual == "lossless" else (["high", "medium"] if pref_qual == "high" else ["medium"])
        
        stream_loc = None
        for q in qual_order:
            try:
                await asyncio.sleep(random.uniform(0.1, 0.3))
                sd = await active_client.get_track_download(track_id, QUALITY_MAP[q])
                if sd.get('location'):
                    stream_loc = sd.get('location')
                    metadata['quality'] = "FLAC" if q == "lossless" else ("AAC 256" if q == "high" else "AAC 128")
                    metadata['extension'] = "flac" if q == "lossless" else "m4a"
                    break
            except: continue
            
        if not stream_loc: raise BeatportError("Gagal mendapatkan link download.")
        metadata['download_url'] = stream_loc
    else:
        metadata['download_url'] = None

    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    if not active_client: raise BeatportError("No Beatport Account.")

    # 1. Fetch Album Info
    album_data = await active_client.get_release(album_id)
    if not album_data: raise BeatportError("Album not found.")
    
    # 2. Get Tracks - Robust Pagination
    tracks_raw = album_data.get("tracks", [])
    need_full_fetch = not tracks_raw or (tracks_raw and isinstance(tracks_raw[0], str))
        
    if need_full_fetch:
        tracks_raw = []
        p = 1
        while True:
            try:
                res = await active_client.get_release_tracks(album_id, page=p)
                if not res.get("results"): break
                tracks_raw.extend(res.get("results"))
                if not res.get("next"): break
                p += 1
                await asyncio.sleep(0.5)
            except: break

    # --- SETUP METADATA ALBUM ---
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = album_id
    metadata['title'] = album_data.get("name")
    metadata['album'] = metadata['title']
    metadata['artist'] = album_data.get("artists", [{}])[0].get("name", "Unknown")
    metadata['type'] = 'album'
    metadata['provider'] = 'Beatport'

    metadata['date'] = album_data.get("publish_date", "")[:10]
    metadata['year'] = metadata['date'][:4]
    metadata['totaltracks'] = str(len(tracks_raw))
    metadata['totalvolume'] = "1"
    
    pref_qual = beatport_manager.get_user_quality(user_id)
    metadata['quality'] = pref_qual.capitalize()

    bp_cover = await _generate_artwork_url(album_data.get("image", {}).get("dynamic_uri"))
    metadata['cover'] = await _process_cover(metadata, bp_cover)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover, 80), metadata, True)

    metadata['tracks'] = []
    
    # FORCE TRACK NUMBERING
    album_explicit = False
    
    for i, track_item in enumerate(tracks_raw):
        try:
            t_data = track_item
            t_id = None
            
            if isinstance(track_item, dict):
                t_id = track_item.get('id')
                if not t_id and track_item.get('track'): 
                    t_data = track_item.get('track')
                    t_id = t_data.get('id')
            elif isinstance(track_item, str):
                t_id = track_item.split('/')[-1]

            if not t_id: continue

            # Proses Track
            t_meta = await process_track_metadata(str(t_id), r_id, user, 
                                                pre_data=t_data if isinstance(t_data, dict) else None, 
                                                fetch_stream=False, 
                                                album_pre_data=album_data)
            
            # PAKSA NOMOR TRACK
            t_meta['tracknumber'] = str(i + 1).zfill(2)
            t_meta['totaltracks'] = metadata['totaltracks']
            
            # Wariskan cover album ke track
            t_meta['cover'] = metadata['cover']
            
            # Update explicit status album
            if t_meta.get('explicit'): album_explicit = True
                
            metadata['tracks'].append(t_meta)
            
        except Exception as e:
            LOGGER.error(f"Skip track {i+1}: {e}")
            continue

    metadata['explicit'] = album_explicit
    if not metadata['tracks']: raise BeatportError("Album kosong/Gagal memproses track.")
        
    return metadata

async def process_playlist_metadata(playlist_id: str, r_id: str, user: dict, extra: dict):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    is_chart = extra.get("is_chart")
    
    if is_chart: pl_data = await active_client.get_chart(playlist_id)
    else: pl_data = await active_client.get_playlist(playlist_id)
    
    tracks = []
    p = 1
    while True:
        try:
            if is_chart: res = await active_client.get_chart_tracks(playlist_id, page=p)
            else: res = await active_client.get_playlist_tracks(playlist_id, page=p)
            if not res.get("results"): break
            tracks.extend(res.get("results"))
            if len(tracks) >= res.get("count", 0): break
            p += 1
            await asyncio.sleep(0.5) 
        except: break

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['title'] = pl_data.get("name")
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Beatport'
    
    metadata['totaltracks'] = str(len(tracks))
    pref_qual = beatport_manager.get_user_quality(user_id)
    metadata['quality'] = pref_qual.capitalize()

    img_uri = pl_data.get("image", {}).get("dynamic_uri")
    if not img_uri and not is_chart and pl_data.get("release_images"):
        img_uri = pl_data.get("release_images")[0] 
        
    bp_cover = await _generate_artwork_url(img_uri)
    metadata['cover'] = await _process_cover(metadata, bp_cover)

    metadata['tracks'] = []
    
    # Cache album sederhana
    album_cache = {}

    for i, t_item in enumerate(tracks):
        try:
            raw_t = t_item.get("track") if not is_chart else t_item
            if not raw_t: continue
            
            # Smart Cache Release Data
            rel_id = raw_t.get("release", {}).get("id")
            alb_dat = None
            if rel_id:
                if rel_id in album_cache: alb_dat = album_cache[rel_id]
                else:
                    try:
                        alb_dat = await active_client.get_release(rel_id)
                        album_cache[rel_id] = alb_dat
                        await asyncio.sleep(0.2) 
                    except: pass

            t_meta = await process_track_metadata(str(raw_t['id']), r_id, user, 
                                                pre_data=raw_t, 
                                                fetch_stream=False, 
                                                album_pre_data=alb_dat)
            
            # Fix Numbering for Playlist
            t_meta['tracknumber'] = str(i + 1).zfill(2)
            metadata['tracks'].append(t_meta)
        except: continue
        
    return metadata
