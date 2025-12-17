# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
import aiohttp
import json
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
# HAPUS moov_manager dari sini untuk mencegah circular import
from bot.logger import LOGGER

def is_explicit_strict(data):
    val_exp = str(data.get('explicit', '')).lower()
    if val_exp in ['true', '1', 'yes', 'explicit']: return True
    val_pw = str(data.get('parentalWarning', '')).lower()
    if val_pw in ['true', '1', 'yes', 'explicit']: return True
    return False

def get_moov_cover(url):
    if not url: return None
    clean_url = url.split("?")[0]
    if "resize" in clean_url:
        return re.sub(r'\/(\d+x\d+)\/', '/1000x1000/', clean_url)
    return clean_url

# --- FUNGSI PENCARI LAGU REKURSIF (DIPERBARUI) ---
def find_products_recursive(data, results=None):
    if results is None: results = []
    
    if isinstance(data, dict):
        # Cek apakah dict ini adalah Track? 
        # Cek productId/contentId DAN title/productTitle
        pid = data.get('productId') or data.get('contentId') or data.get('mtgContentId')
        title = data.get('productTitle') or data.get('title') or data.get('trackTitle')
        
        # Syarat tambahan: Harus punya 'artist' atau 'artists' agar tidak salah ambil Album sebagai Track
        has_artist = 'artist' in data or 'artists' in data
        
        if pid and title and has_artist:
            # Pastikan bukan duplikat ID
            if not any(x.get('productId') == pid for x in results):
                # Normalisasi ID ke 'productId'
                data['productId'] = pid
                data['productTitle'] = title
                results.append(data)
            return

        for key, value in data.items():
            if isinstance(value, (dict, list)):
                 find_products_recursive(value, results)
                 
    elif isinstance(data, list):
        for item in data:
            find_products_recursive(item, results)
            
    return results
# -------------------------------------------------

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    # --- LOCAL IMPORT (FIX CIRCULAR IMPORT) ---
    from .manager import moov_manager
    # ------------------------------------------

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    artists = track_data.get('artists', [])
    if not artists and 'artist' in track_data:
        # Handle jika format artist beda (misal string)
        if isinstance(track_data['artist'], str):
             metadata['artist'] = track_data['artist']
        else:
             artists = [track_data['artist']]
    
    if artists:
        if isinstance(artists, list):
            main_artists = [a.get('name') for a in artists if isinstance(a, dict) and a.get('role') == 'Main']
            if not main_artists: main_artists = [a.get('name') for a in artists if isinstance(a, dict)]
            metadata['artist'] = ", ".join(main_artists)
        
    metadata['album'] = track_data.get('albumTitle') or ""
    metadata['disk'] = str(track_data.get('discNo', 1))
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    metadata['label'] = track_data.get('albumLabel', '') 
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""
    
    comp_list = []
    if 'composers' in track_data:
        for c in track_data.get('composers', []):
            if isinstance(c, dict): comp_list.append(c.get('name'))
    if not comp_list and track_data.get('author'):
        comp_list.append(track_data.get('author'))
    metadata['composer'] = ", ".join(comp_list)

    is_track_explicit = is_explicit_strict(track_data)
    metadata['explicit'] = "True" if is_track_explicit else "False"

    track_date_raw = str(track_data.get('publishDate', ''))
    if not track_date_raw: track_date_raw = str(track_data.get('releaseDate', ''))
    if 'T' in track_date_raw: track_date_raw = track_date_raw.split('T')[0]
        
    if track_date_raw:
        metadata['date'] = track_date_raw
        metadata['year'] = track_date_raw[:4]
    
    if album_meta:
        if not metadata['albumartist']: metadata['albumartist'] = album_meta.get('artist', '')
        if not metadata['genre']: metadata['genre'] = album_meta.get('genre', '')
        
        if album_meta.get('type') == 'album':
            metadata['totaltracks'] = album_meta.get('totaltracks', '')
            metadata['totalvolumes'] = album_meta.get('totalvolumes', '')
        
        if not metadata.get('date'):
            metadata['date'] = album_meta.get('date', '')
            metadata['year'] = album_meta.get('year', '')
            
        if not metadata['label']: metadata['label'] = album_meta.get('label', '')
        if not metadata['copyright']: metadata['copyright'] = album_meta.get('copyright', '')
            
        if not cover and album_meta.get('cover_url'):
             metadata['cover_url'] = album_meta.get('cover_url')
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    if cover:
        metadata['cover'] = cover
    elif not metadata.get('cover_url'):
        images = track_data.get('images', [])
        if images:
            raw_url = images[0].get('path')
            metadata['cover_url'] = get_moov_cover(raw_url)
            metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)

    avail_qualities = track_data.get('qualities', [])
    
    user_pref = moov_manager.get_user_quality(user['user_id']) 
    
    target_quality = 'LL' 
    if user_pref == "FLAC": 
        if 'HR' in avail_qualities:
            target_quality = 'HR'
            metadata['quality'] = 'FLAC 24bit'
        elif 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
    else: 
        if 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
            
    metadata['extension'] = 'flac'
    metadata['moov_quality_code'] = target_quality
    
    return metadata

async def process_album_metadata(album_data: dict, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    titles = album_data.get('engTitle', [])
    if not titles: titles = album_data.get('title', [])
        
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 

    is_album_explicit = is_explicit_strict(album_data)
    tags = album_data.get('tags', [])
    if 'Explicit' in tags or 'Parental Advisory' in tags:
        is_album_explicit = True

    moov_date = ""
    moov_year = ""
    if len(titles) > 2:
        moov_date = titles[2]
        try: moov_year = moov_date.split('-')[0]
        except: pass
    if not moov_date:
        pdate = str(album_data.get('publishDate', ''))
        if pdate: 
            if 'T' in pdate: pdate = pdate.split('T')[0]
            moov_date = pdate
            moov_year = pdate.split('-')[0]
            
    metadata['year'] = moov_year
    metadata['date'] = moov_date 

    genres = album_data.get('genres', [])
    if genres:
        metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else:
        metadata['genre'] = album_data.get('category', "")
        
    metadata['label'] = album_data.get('recordLabel') or album_data.get('albumLabel') or ""

    moov_cover_url = None
    images = album_data.get('images', [])
    if images:
        raw_path = images[0].get('path')
        moov_cover_url = get_moov_cover(raw_path)

    metadata['cover_url'] = moov_cover_url
    if metadata.get('cover_url'):
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)
        
    metadata['tracks'] = []
    
    raw_products = find_products_recursive(album_data)
    
    max_disc = 1
    for idx, track_raw in enumerate(raw_products, 1):
        track_raw['trackNo'] = idx 
        if not is_album_explicit:
            if is_explicit_strict(track_raw): is_album_explicit = True
        try:
            d = int(track_raw.get('discNo', 1))
            if d > max_disc: max_disc = d
        except: pass
        
        t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
        metadata['tracks'].append(t_meta)
    
    metadata['totaltracks'] = len(metadata['tracks'])
    metadata['totalvolumes'] = str(max_disc)

    metadata['explicit'] = "True" if is_album_explicit else "False"
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata

async def process_playlist_metadata(pl_data: dict, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    titles = pl_data.get('engTitle', [])
    if not titles: titles = pl_data.get('title', []) 
    
    metadata['title'] = titles[0] if titles else "Unknown Playlist"
    metadata['album'] = metadata['title']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'playlist'
    metadata['itemid'] = pl_data.get('profileId')
    
    metadata['artist'] = "Moov Playlist"
    metadata['albumartist'] = "Various Artists"

    images = pl_data.get('images', [])
    if images:
        raw_path = images[0].get('path')
        metadata['cover_url'] = get_moov_cover(raw_path)
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)

    metadata['tracks'] = []
    
    # --- PENGGUNAAN FUNGSI REKURSIF ---
    # Cari semua produk/lagu dimanapun mereka berada dalam JSON
    raw_tracks = find_products_recursive(pl_data)
    
    LOGGER.info(f"Moov Playlist/Chart: Ditemukan {len(raw_tracks)} lagu melalui pencarian rekursif.")
    
    # DEBUG: Jika 0 lagu, log keys utama untuk investigasi (opsional)
    if not raw_tracks:
        LOGGER.warning(f"DEBUG keys utama data: {list(pl_data.keys())}")
        if 'modules' in pl_data:
            LOGGER.warning(f"DEBUG modules count: {len(pl_data['modules'])}")
    # ----------------------------------

    for idx, track_raw in enumerate(raw_tracks, 1):
        track_raw['trackNo'] = idx
        track_raw['discNo'] = 1
        
        t_meta = await process_track_metadata(track_raw, r_id, user, cover=None, album_meta=None)
        
        if not t_meta.get('cover') and metadata.get('cover'):
             t_meta['cover'] = metadata['cover']

        metadata['tracks'].append(t_meta)

    metadata['totaltracks'] = len(metadata['tracks'])
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']

    return metadata
