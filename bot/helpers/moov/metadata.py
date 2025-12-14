# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager

# Fungsi bantuan untuk memaksa resolusi tinggi
def get_high_res_cover(url):
    if not url: return None
    # Pola URL Moov biasanya mengandung resolusi, misal: .../resize/350x350/...
    # Kita ubah menjadi 1000x1000 atau resolusi maksimal
    if "350x350" in url:
        return url.replace("350x350", "1000x1000")
    # Jika pola lain, coba regex umum untuk angka resolusi
    return re.sub(r'\/resize\/\d+x\d+\/', '/resize/1000x1000/', url)

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    artists = track_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    
    metadata['album'] = track_data.get('albumTitle') or ""
    
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""

    metadata['label'] = track_data.get('albumLabel') or ""
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    # --- PERBAIKAN COVER ART (High Res) ---
    if cover:
        metadata['cover'] = cover
    else:
        images = track_data.get('images', [])
        if images:
            # Ambil URL gambar pertama
            raw_url = images[0].get('path')
            # Manipulasi URL untuk mendapatkan resolusi tinggi
            hd_url = get_high_res_cover(raw_url)
            metadata['cover'] = await create_cover_file(hd_url, metadata)
    # --------------------------------------

    # Quality Selection
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
    
    meta_lang_key = 'engTitle' 
    titles = album_data.get(meta_lang_key, [])
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    if len(titles) > 2:
        metadata['date'] = titles[2].split('-')[0] 
        
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 
    
    images = album_data.get('images', [])
    if images:
        # Terapkan High Res juga untuk cover album
        raw_url = images[0].get('path')
        hd_url = get_high_res_cover(raw_url)
        metadata['cover'] = await create_cover_file(hd_url, metadata)
        
    metadata['tracks'] = []
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx 
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'])
            metadata['tracks'].append(t_meta)
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
