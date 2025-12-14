# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager
from bot.logger import LOGGER

def get_high_res_cover(url):
    if not url: return None
    
    # 1. Coba replace langsung string resolusi umum Moov
    new_url = url.replace("350x350", "1000x1000")
    
    # 2. Jika tidak ada perubahan, coba regex untuk format lain (misal /resize/500x500/)
    if new_url == url:
        new_url = re.sub(r'\/resize\/\d+x\d+\/', '/resize/1000x1000/', url)
        
    # 3. Hapus parameter cropping jika ada (agar gambar full)
    # Contoh: ?crop=...
    if "?" in new_url:
        new_url = new_url.split("?")[0]
        
    return new_url

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    artists = track_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    
    metadata['album'] = track_data.get('albumTitle') or ""
    
    # --- DATA EXTRA ---
    metadata['disk'] = str(track_data.get('discNo', 1))
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    # Composer
    composers = track_data.get('composers', [])
    if composers:
        metadata['composer'] = ", ".join([c.get('name') for c in composers])
    else:
        metadata['composer'] = ""
        
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""
    # ------------------

    # Wariskan data dari Album (Year, Genre, Album Artist)
    if album_meta:
        metadata['albumartist'] = album_meta.get('artist', '')
        metadata['year'] = album_meta.get('year', '')
        metadata['genre'] = album_meta.get('genre', '')
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    # --- LOGIKA COVER BARU ---
    if cover:
        metadata['cover'] = cover
    else:
        images = track_data.get('images', [])
        if images:
            raw_url = images[0].get('path')
            hd_url = get_high_res_cover(raw_url)
            # LOGGER.info(f"[DEBUG COVER] Track Cover: {hd_url}")
            metadata['cover'] = await create_cover_file(hd_url, metadata)
    # -------------------------

    # Quality Logic
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
    
    # Parsing Judul & Tanggal
    meta_lang_key = 'engTitle' 
    titles = album_data.get(meta_lang_key, [])
    # titles biasanya: [Nama Album, Nama Artis, Tanggal Rilis]
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    # Parsing Year (Lebih Robust)
    metadata['year'] = ""
    if len(titles) > 2:
        try:
            metadata['year'] = titles[2].split('-')[0]
        except: pass
        
    if not metadata['year']:
        # Fallback ke publishDate jika ada
        pdate = str(album_data.get('publishDate', ''))
        if pdate:
            metadata['year'] = pdate.split('-')[0]

    # Parsing Genre
    genres = album_data.get('genres', [])
    if genres:
        metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else:
        metadata['genre'] = ""

    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 
    
    # --- COVER ALBUM HIGH RES ---
    images = album_data.get('images', [])
    if images:
        raw_url = images[0].get('path')
        hd_url = get_high_res_cover(raw_url)
        # LOGGER.info(f"[DEBUG COVER] Album Cover: {hd_url}")
        metadata['cover'] = await create_cover_file(hd_url, metadata)
        
    metadata['tracks'] = []
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx 
            # Kirim 'metadata' album sebagai parent
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
            metadata['tracks'].append(t_meta)
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
