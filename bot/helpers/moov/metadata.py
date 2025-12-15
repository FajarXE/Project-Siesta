# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
import urllib.parse
import aiohttp
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager
from bot.logger import LOGGER

async def fetch_itunes_meta(artist, album):
    if not artist or not album: return None
    
    term = f"{artist} {album}"
    query = urllib.parse.quote(term)
    url = f"https://itunes.apple.com/search?term={query}&entity=album&limit=1"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    
                    if data['resultCount'] > 0:
                        res = data['results'][0]
                        
                        raw_art = res.get('artworkUrl100', '')
                        hd_cover = raw_art.replace('100x100bb', '3000x3000bb')
                        
                        release_date = res.get('releaseDate', '')
                        if 'T' in release_date:
                            release_date = release_date.split('T')[0]
                        
                        return {
                            'cover_url': hd_cover,
                            'genre': res.get('primaryGenreName', ''),
                            'date': release_date,
                            'year': release_date[:4] if release_date else '',
                            'copyright': res.get('copyright', ''),
                            'composer': '',
                            'track_count': res.get('trackCount'),
                            # UBAH DISINI: Yes/No -> True/False
                            'explicit': 'True' if res.get('collectionExplicitness') == 'explicit' else 'False'
                        }
    except Exception as e:
        LOGGER.error(f"iTunes Search Error: {e}")
        
    return None

def get_moov_cover(url):
    if not url: return None
    clean_url = url.split("?")[0]
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

    # Date Logic
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
        metadata['explicit'] = album_meta.get('explicit', 'False') # Default False
        
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
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 

    # --- EXPLICIT CHECK ---
    is_explicit = False
    if album_data.get('explicit') or album_data.get('parentalWarning'):
        is_explicit = True
    
    tags = album_data.get('tags', [])
    if 'Explicit' in tags or 'Parental Advisory' in tags:
        is_explicit = True

    # Date
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
        moov_cover_url = get_moov_cover(images[0].get('path'))

    # iTunes Search
    itunes_data = await fetch_itunes_meta(metadata['artist'], metadata['album'])
    
    if itunes_data:
        LOGGER.info(f"[ITUNES] Match Found: {metadata['album']}")
        metadata['cover_url'] = itunes_data['cover_url']
        if itunes_data['genre']: metadata['genre'] = itunes_data['genre']
        if itunes_data['copyright']: metadata['copyright'] = itunes_data['copyright']
        
        if itunes_data.get('explicit') == 'True':
            is_explicit = True
            
        if not metadata['date'] and itunes_data['date']:
             metadata['date'] = itunes_data['date']
             metadata['year'] = itunes_data['year']
    else:
        metadata['cover_url'] = moov_cover_url

    # UBAH DISINI: Yes/No -> True/False
    metadata['explicit'] = "True" if is_explicit else "False"

    if metadata.get('cover_url'):
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)
        
    metadata['tracks'] = []
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx 
            
            # Update Explicit Logic Per Track
            if not is_explicit:
                if track_raw.get('explicit') or track_raw.get('parentalWarning'):
                    is_explicit = True
                    metadata['explicit'] = "True" # Update parent status jika ada track explicit
            
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
            metadata['tracks'].append(t_meta)
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
