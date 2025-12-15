# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
import aiohttp
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager
from bot.logger import LOGGER

def is_explicit_strict(data):
    """
    Fungsi bantu untuk mengecek status explicit secara ketat.
    """
    val_exp = str(data.get('explicit', '')).lower()
    if val_exp in ['true', '1', 'yes', 'explicit']:
        return True
        
    val_pw = str(data.get('parentalWarning', '')).lower()
    if val_pw in ['true', '1', 'yes', 'explicit']:
        return True
        
    return False

def get_moov_cover(url):
    """
    Mengambil URL cover Moov dan mencoba menaikkan resolusi ke 1000x1000
    """
    if not url: return None
    clean_url = url.split("?")[0]
    
    # Moov biasanya memiliki pola /resize/WIDTHxHEIGHT/ di URL gambarnya
    if "resize" in clean_url:
        return re.sub(r'\/(\d+x\d+)\/', '/1000x1000/', clean_url)
        
    return clean_url

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    artists = track_data.get('artists', [])
    main_artists = [a.get('name') for a in artists if a.get('role') == 'Main']
    if not main_artists: main_artists = [a.get('name') for a in artists]
    metadata['artist'] = ", ".join(main_artists)
    
    metadata['album'] = track_data.get('albumTitle') or ""
    metadata['disk'] = str(track_data.get('discNo', 1))
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    metadata['label'] = track_data.get('albumLabel', '') 
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""
    
    comp_list = []
    for c in track_data.get('composers', []):
        comp_list.append(c.get('name'))
    if not comp_list and track_data.get('author'):
        comp_list.append(track_data.get('author'))
    metadata['composer'] = ", ".join(comp_list)

    # --- EXPLICIT TRACK ---
    is_track_explicit = is_explicit_strict(track_data)
    metadata['explicit'] = "True" if is_track_explicit else "False"

    # --- DATE LOGIC ---
    track_date_raw = str(track_data.get('publishDate', ''))
    if not track_date_raw: track_date_raw = str(track_data.get('releaseDate', ''))
    
    if 'T' in track_date_raw: track_date_raw = track_date_raw.split('T')[0]
        
    if track_date_raw:
        metadata['date'] = track_date_raw
        metadata['year'] = track_date_raw[:4]
    
    # Wariskan data Album
    if album_meta:
        metadata['albumartist'] = album_meta.get('artist', '')
        metadata['genre'] = album_meta.get('genre', '')
        metadata['totaltracks'] = album_meta.get('totaltracks', '')
        
        # Fallback date ke album jika track kosong
        if not metadata.get('date'):
            metadata['date'] = album_meta.get('date', '')
            metadata['year'] = album_meta.get('year', '')
            
        if not metadata['label']: metadata['label'] = album_meta.get('label', '')
        if not metadata['copyright']: metadata['copyright'] = album_meta.get('copyright', '')
            
        # Gunakan Cover Album
        if not cover and album_meta.get('cover_url'):
             metadata['cover_url'] = album_meta.get('cover_url')
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    # Cover Handling
    if cover:
        metadata['cover'] = cover
    elif not metadata.get('cover_url'):
        images = track_data.get('images', [])
        if images:
            raw_url = images[0].get('path')
            metadata['cover_url'] = get_moov_cover(raw_url)
            metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)

    # Quality Handling
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
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 

    # --- EXPLICIT CHECK (ALBUM) ---
    is_album_explicit = is_explicit_strict(album_data)
    
    tags = album_data.get('tags', [])
    if 'Explicit' in tags or 'Parental Advisory' in tags:
        is_album_explicit = True

    # --- DATE ---
    moov_date = ""
    moov_year = ""
    # Moov sering menaruh tanggal di elemen ke-3 list engTitle
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

    # --- GENRE ---
    genres = album_data.get('genres', [])
    if genres:
        metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else:
        metadata['genre'] = album_data.get('category', "")
        
    metadata['label'] = album_data.get('recordLabel') or album_data.get('albumLabel') or ""

    # --- COVER (MOOV ONLY) ---
    moov_cover_url = None
    images = album_data.get('images', [])
    if images:
        raw_path = images[0].get('path')
        # Fungsi ini akan otomatis mengubah resolusi ke 1000x1000 jika memungkinkan
        moov_cover_url = get_moov_cover(raw_path)

    metadata['cover_url'] = moov_cover_url

    # Download Cover Utama
    if metadata.get('cover_url'):
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)
        
    metadata['tracks'] = []
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx 
            
            # Cek jika ada lagu explicit, update status album
            if not is_album_explicit:
                if is_explicit_strict(track_raw):
                    is_album_explicit = True
            
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
            metadata['tracks'].append(t_meta)
            
    # Set status Poster Album
    metadata['explicit'] = "True" if is_album_explicit else "False"
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
