# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager
from bot.logger import LOGGER

def get_high_res_cover(url):
    if not url: return None
    
    clean_url = url.split("?")[0]
    
    # Logic: Ganti resolusi apapun menjadi 1000x1000
    # Moov pattern: .../resize/350x350/...
    if "resize" in clean_url:
        clean_url = re.sub(r'\/(\d+x\d+)\/', '/1000x1000/', clean_url)
    
    # Jika tidak ada resize pattern, biarkan (biasanya sudah source)
    return clean_url

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    artists = track_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    
    metadata['album'] = track_data.get('albumTitle') or ""
    metadata['disk'] = str(track_data.get('discNo', 1))
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    # --- COMPOSER EXTRACTION ---
    composers = track_data.get('composers', [])
    if composers:
        metadata['composer'] = ", ".join([c.get('name') for c in composers])
    elif track_data.get('author'):
        metadata['composer'] = track_data.get('author')
    else:
        # Coba wariskan dari album jika tidak ada di track
        metadata['composer'] = ""
        
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""

    # Wariskan data Album
    if album_meta:
        metadata['albumartist'] = album_meta.get('artist', '')
        metadata['year'] = album_meta.get('year', '')
        metadata['genre'] = album_meta.get('genre', '')
        # Jika track tidak punya cover, pakai cover album
        if not cover and album_meta.get('cover_url'):
             metadata['cover_url'] = album_meta.get('cover_url')
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    # --- COVER LOGIC ---
    # Kita simpan URL High Res secara terpisah untuk Handler
    if cover:
        metadata['cover'] = cover
        # Jika cover sudah didownload di level album, URLnya mungkin ada di album_meta
        if album_meta:
            metadata['cover_url'] = album_meta.get('cover_url')
    else:
        images = track_data.get('images', [])
        if images:
            raw_url = images[0].get('path')
            hd_url = get_high_res_cover(raw_url)
            
            # PENTING: Simpan URL ini!
            metadata['cover_url'] = hd_url 
            # Download file lokal untuk Poster Telegram
            metadata['cover'] = await create_cover_file(hd_url, metadata)
    # -------------------

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
    
    # Parsing Year
    metadata['year'] = ""
    if len(titles) > 2:
        try:
            metadata['year'] = titles[2].split('-')[0]
        except: pass
    if not metadata['year']:
        pdate = str(album_data.get('publishDate', ''))
        if pdate: metadata['year'] = pdate.split('-')[0]

    # --- GENRE EXTRACTION ---
    genres = album_data.get('genres', [])
    if genres:
        metadata['genre'] = ", ".join([g.get('name') for g in genres])
    elif album_data.get('category'):
        metadata['genre'] = album_data.get('category')
    else:
        metadata['genre'] = ""

    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 
    
    images = album_data.get('images', [])
    if images:
        raw_url = images[0].get('path')
        hd_url = get_high_res_cover(raw_url)
        
        # PENTING: Simpan URL High Res
        metadata['cover_url'] = hd_url
        # Download untuk poster
        metadata['cover'] = await create_cover_file(hd_url, metadata)
        
    metadata['tracks'] = []
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx 
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
            metadata['tracks'].append(t_meta)
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
