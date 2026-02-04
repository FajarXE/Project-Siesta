# [GANTI SELURUH FILE: bot/helpers/beatsource/metadata.py]

import copy
import re
import aiohttp
import os
import asyncio
import random
from config import Config 

# Import Mutagen untuk Tagging Lokal
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import TBPM, TKEY, TXXX, TPUB, TSRC, TPE4

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .api import BeatsourceAPI, BeatsourceError
from .manager import beatsource_manager
from bot.logger import LOGGER

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

# --- FUNGSI TAGGING LOKAL (DIPERBARUI LENGKAP) ---
async def write_extended_tags(filepath: str, meta: dict):
    """
    Menulis tag khusus Beatsource: BPM, Key, CatNo, Label, UPC, ISRC, Barcode, Producer.
    """
    try:
        ext = os.path.splitext(filepath)[1].lower()
        
        # 1. Handler M4A (iTunes) - [UPDATE LENGKAP]
        if ext in ['.m4a', '.mp4']:
            audio = MP4(filepath)
            
            # --- BPM ---
            if meta.get('bpm'):
                try: audio.tags['tmpo'] = [int(float(meta['bpm']))]
                except: audio.tags['----:com.apple.iTunes:BPM'] = str(meta['bpm']).encode('utf-8')

            # --- KEY ---
            if meta.get('key'):
                audio.tags['----:com.apple.iTunes:initialkey'] = str(meta['key']).encode('utf-8')
                audio.tags['----:com.apple.iTunes:KEY'] = str(meta['key']).encode('utf-8')

            # --- CATALOG NUMBER ---
            if meta.get('catalog_number'):
                audio.tags['----:com.apple.iTunes:CATALOGNUMBER'] = str(meta['catalog_number']).encode('utf-8')

            # --- LABEL / PUBLISHER ---
            if meta.get('label'):
                audio.tags['----:com.apple.iTunes:LABEL'] = str(meta['label']).encode('utf-8')
                audio.tags['\u00a9pub'] = meta['label']

            # --- ISRC ---
            if meta.get('isrc'):
                audio.tags['----:com.apple.iTunes:ISRC'] = str(meta['isrc']).encode('utf-8')

            # --- UPC / BARCODE ---
            if meta.get('upc'):
                audio.tags['----:com.apple.iTunes:UPC'] = str(meta['upc']).encode('utf-8')
                audio.tags['----:com.apple.iTunes:BARCODE'] = str(meta['upc']).encode('utf-8')

            # --- PRODUCER / REMIXER ---
            if meta.get('remixer'):
                audio.tags['----:com.apple.iTunes:REMIXER'] = str(meta['remixer']).encode('utf-8')
            
            # (Opsional) Mapping Producer ke atom standar iTunes jika ada data
            if meta.get('producer'):
                audio.tags['\u00a9prd'] = meta['producer']

            audio.save()

        # 2. Handler FLAC - [UPDATE LENGKAP]
        elif ext == '.flac':
            audio = FLAC(filepath)
            
            if meta.get('bpm'): audio.tags['BPM'] = str(meta['bpm'])
            
            # Key: InitialKey dan Key biasa
            if meta.get('key'): 
                audio.tags['INITIALKEY'] = str(meta['key'])
                audio.tags['KEY'] = str(meta['key'])
            
            if meta.get('catalog_number'): audio.tags['CATALOGNUMBER'] = str(meta['catalog_number'])
            
            # Label & Publisher
            if meta.get('label'): 
                audio.tags['LABEL'] = meta['label']
                audio.tags['ORGANIZATION'] = meta['label']
                audio.tags['PUBLISHER'] = meta['label'] # User Request
            
            if meta.get('isrc'): audio.tags['ISRC'] = str(meta['isrc'])
            
            # UPC & Barcode
            if meta.get('upc'):
                audio.tags['UPC'] = str(meta['upc'])
                audio.tags['BARCODE'] = str(meta['upc']) # User Request

            if meta.get('remixer'): audio.tags['REMIXER'] = str(meta['remixer'])

            audio.save()

        # 3. Handler MP3
        elif ext == '.mp3':
            audio = MP3(filepath, ID3=EasyMP3)
            from mutagen.id3 import ID3
            tags = ID3(filepath)
            
            if meta.get('bpm'): tags.add(TBPM(encoding=3, text=str(meta['bpm'])))
            if meta.get('key'): tags.add(TKEY(encoding=3, text=str(meta['key'])))
            if meta.get('catalog_number'): tags.add(TXXX(encoding=3, desc='CATALOGNUMBER', text=str(meta['catalog_number'])))
            if meta.get('label'): tags.add(TPUB(encoding=3, text=meta['label']))
            if meta.get('isrc'): tags.add(TSRC(encoding=3, text=str(meta['isrc'])))
            if meta.get('remixer'): tags.add(TPE4(encoding=3, text=str(meta['remixer'])))
            if meta.get('upc'): tags.add(TXXX(encoding=3, desc='BARCODE', text=str(meta['upc'])))
            
            tags.save()

    except Exception as e:
        LOGGER.warning(f"Gagal menulis extended tags Beatsource: {e}")

# --- PROSES METADATA INTI ---

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

    # 1. Fetch Track Data
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

    # 3. Fill Metadata Standar
    meta['title'] = track_data.get('name')
    if track_data.get('mix_name'): meta['title'] += f" ({track_data['mix_name']})"
    
    meta['artist'] = ", ".join([a['name'] for a in track_data.get("artists", [])])
    
    # [NEW] Ambil Remixer sebagai Proxy untuk Producer
    remixers = track_data.get("remixers", [])
    if not remixers: remixers = track_data.get("bsrc_remixer", []) # Fallback key
    
    remixer_raw = ", ".join([r.get("name") for r in remixers])
    meta['remixer'] = remixer_raw
    # Gunakan Remixer sebagai Producer jika diminta
    meta['producer'] = remixer_raw 

    meta['album'] = release_data.get('name')
    meta['albumartist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    meta['date'] = release_data.get('publish_date', '')[:10]
    meta['year'] = meta['date'][:4]
    meta['explicit'] = track_data.get("explicit", False)
    meta['duration'] = track_data.get('length_ms', 0) // 1000

    meta['tracknumber'] = str(track_data.get('track_number', 1)).zfill(2)
    meta['totaltracks'] = str(release_data.get('track_count', 1))
    
    # [DATA EKSTRA LENGKAP]
    meta['bpm'] = str(track_data.get('bpm', ''))
    
    key_data = track_data.get('key')
    if isinstance(key_data, dict): meta['key'] = key_data.get('name')
    else: meta['key'] = str(key_data) if key_data else ''

    # Catalog & Label
    meta['catalog_number'] = track_data.get('catalog_number') or release_data.get('catalog_number', '')
    meta['label'] = release_data.get('label', {}).get('name', '')
    meta['publisher'] = meta['label']

    # [BARU] ISRC & UPC
    meta['isrc'] = track_data.get('isrc', '')
    meta['upc'] = track_data.get('release', {}).get('upc') or release_data.get('upc', '')

    # Cover
    img = release_data.get('image', {}).get('dynamic_uri') or track_data.get('image', {}).get('dynamic_uri')
    if img:
        img_url = await _generate_artwork_url(img)
        meta['cover'] = await _process_cover(meta, img_url)
        meta['thumbnail'] = await create_cover_file(await _generate_artwork_url(img, 400), meta, thumbnail=True)

    # 4. Stream Logic
    user_qual = beatsource_manager.get_user_quality(user_id)
    meta['quality'] = user_qual.capitalize()
    meta['extension'] = 'flac' if user_qual == 'lossless' else 'm4a'
    
    if fetch_stream:
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

    release_data = await active_client.get_release(item_id)
    if not release_data: raise BeatsourceError("Album not found.")
    
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

    meta = copy.deepcopy(base_meta)
    meta['provider'] = 'Beatsource'
    meta['tempfolder'] += f"{r_id}/Beatsource/{item_id}_ALBUM"
    meta['type'] = 'album'
    meta['title'] = release_data['name']
    meta['artist'] = ", ".join([a['name'] for a in release_data.get("artists", [])])
    
    meta['date'] = release_data.get('publish_date', '')[:10]
    meta['year'] = meta['date'][:4]
    meta['totaltracks'] = str(len(tracks))
    meta['totalvolume'] = "1"
    
    pref_qual = beatsource_manager.get_user_quality(user_id)
    meta['quality'] = pref_qual.capitalize()
    
    img = release_data.get('image', {}).get('dynamic_uri')
    if img:
        img_url = await _generate_artwork_url(img)
        meta['cover'] = await _process_cover(meta, img_url)
        meta['thumbnail'] = await create_cover_file(await _generate_artwork_url(img, 400), meta, thumbnail=True)

    meta['tracks'] = []
    album_explicit = False

    for i, t in enumerate(tracks):
        try:
            tm = await process_track_metadata(str(t['id']), r_id, user, 
                                            fetch_stream=False, 
                                            pre_data=t, 
                                            album_pre_data=release_data)
            
            tm['tracknumber'] = str(i + 1).zfill(2)
            tm['totaltracks'] = meta['totaltracks']
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
    
    if is_chart: pl_data = await active_client.get_chart(item_id)
    else: pl_data = await active_client.get_playlist(item_id)
    
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
            
            tm['tracknumber'] = str(i + 1).zfill(2)
            meta['tracks'].append(tm)
        except: continue

    return meta
