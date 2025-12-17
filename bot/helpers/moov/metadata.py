# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
import aiohttp
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
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
    clean_url = re.sub(r'\/resize\/\d+x\d+', '', clean_url)
    clean_url = re.sub(r'_(\d{2,4}x\d{2,4})', '', clean_url)
    clean_url = clean_url.replace('//', '/').replace('https:/', 'https://').replace('http:/', 'http://')
    return clean_url

def parse_date(date_val):
    if not date_val: return None
    s = str(date_val).strip()
    if s.lower() == 'none' or s == "": return None
    if 'T' in s: return s.split('T')[0]
    if len(s) == 8 and s.isdigit(): return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    return None

def find_products_recursive(data, results=None):
    if results is None: results = []
    if isinstance(data, dict):
        pid = data.get('productId') or data.get('contentId') or data.get('mtgContentId')
        title = data.get('productTitle') or data.get('title') or data.get('trackTitle')
        if pid and title:
            if not any(x.get('productId') == pid for x in results):
                data['productId'] = pid
                data['productTitle'] = title
                results.append(data)
            return
        for key, value in data.items():
            if isinstance(value, (dict, list)): find_products_recursive(value, results)
    elif isinstance(data, list):
        for item in data: find_products_recursive(item, results)
    return results

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    from .manager import moov_manager

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')

    # --- TAMBAHAN PENTING: SIMPAN ALBUM ID UNTUK FALLBACK ---
    if track_data.get('albumId'):
        metadata['moov_album_id'] = track_data.get('albumId')
    elif isinstance(track_data.get('album'), dict):
        metadata['moov_album_id'] = track_data.get('album').get('id')
    # --------------------------------------------------------
    
    # --- PENGOLAHAN ARTIS & PRODUCER (Deep Search) ---
    artists_raw = track_data.get('artists', [])
    if not artists_raw and 'artist' in track_data:
        if isinstance(track_data['artist'], str): 
            artists_raw = [{'name': track_data['artist'], 'role': 'Main'}]
        else: 
            artists_raw = [track_data['artist']]

    main_artists = []
    producers = []
    
    if isinstance(artists_raw, list):
        for a in artists_raw:
            if isinstance(a, dict):
                name = a.get('name')
                role = a.get('role', 'Main')
                if role in ['Main', 'Featured']:
                    main_artists.append(name)
                if role in ['Producer', 'Arranger', 'Composer', 'Conductor']:
                    producers.append(name)
            elif isinstance(a, str):
                main_artists.append(a)
    
    metadata['artist'] = ", ".join(main_artists)
    metadata['producer'] = ", ".join(producers) 
    
    label_val = ""
    label_keys = ['albumLabel', 'label', 'recordLabel', 'company', 'copyright']
    for key in label_keys:
        val = track_data.get(key)
        if val:
            label_val = val
            break
            
    if not label_val and 'album' in track_data:
        alb = track_data.get('album')
        if isinstance(alb, dict):
            for key in label_keys:
                val = alb.get(key)
                if val:
                    label_val = val
                    break
    
    metadata['label'] = str(label_val)

    if track_data.get('albumTitle'):
        metadata['album'] = track_data.get('albumTitle')
    elif album_meta:
        metadata['album'] = album_meta.get('title', '')
    else:
        metadata['album'] = ""

    metadata['albumartist'] = metadata['artist'] 
    if album_meta and album_meta.get('artist'):
         metadata['albumartist'] = album_meta.get('artist')

    metadata['disk'] = str(track_data.get('discNo', 1))
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
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

    final_date = None
    date_keys = ['publishDate', 'releaseDate', 'originalReleaseDate', 'createdOn']
    for key in date_keys:
        d = parse_date(track_data.get(key))
        if d: 
            final_date = d
            break
    if not final_date and 'album' in track_data:
        alb_data = track_data.get('album')
        if isinstance(alb_data, dict):
            for key in date_keys:
                d = parse_date(alb_data.get(key))
                if d:
                    final_date = d
                    break
    
    if final_date:
        metadata['date'] = final_date
        metadata['year'] = final_date[:4]
    
    if album_meta:
        if not metadata.get('date'):
            metadata['date'] = album_meta.get('date', '')
            metadata['year'] = album_meta.get('year', '')
        if not metadata['label']: metadata['label'] = album_meta.get('label', '')
        if not metadata['copyright']: metadata['copyright'] = album_meta.get('copyright', '')

    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    if cover:
        metadata['cover'] = cover
    elif not metadata.get('cover_url'):
        found_url = None
        if track_data.get('largeImage'):
            found_url = track_data.get('largeImage')
        
        if not found_url and 'album' in track_data:
            alb = track_data.get('album')
            if isinstance(alb, dict):
                if alb.get('largeImage'): found_url = alb.get('largeImage')
                elif alb.get('images'): found_url = alb.get('images')[0].get('path')

        if not found_url:
            images = track_data.get('images', [])
            if images: found_url = images[0].get('path')

        if not found_url: found_url = track_data.get('thumbnail')

        if found_url:
            metadata['cover_url'] = get_moov_cover(found_url)
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
    
    final_date = None
    date_keys = ['publishDate', 'releaseDate', 'originalReleaseDate']
    for key in date_keys:
        d = parse_date(album_data.get(key))
        if d: 
            final_date = d
            break
    if final_date:
        metadata['date'] = final_date
        metadata['year'] = final_date[:4]
    else:
        if len(titles) > 2:
            try: 
                metadata['year'] = titles[2].split('-')[0]
                metadata['date'] = titles[2]
            except: pass

    genres = album_data.get('genres', [])
    if genres: metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else: metadata['genre'] = album_data.get('category', "")
        
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
    if metadata['tracks']: metadata['quality'] = metadata['tracks'][0]['quality']
        
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
    raw_tracks = find_products_recursive(pl_data)
    LOGGER.info(f"Moov Playlist/Chart: Ditemukan {len(raw_tracks)} lagu.")

    for idx, track_raw in enumerate(raw_tracks, 1):
        track_raw['trackNo'] = idx
        track_raw['discNo'] = 1
        
        t_meta = await process_track_metadata(track_raw, r_id, user, cover=None, album_meta=None)
        metadata['tracks'].append(t_meta)

    metadata['totaltracks'] = len(metadata['tracks'])
    if metadata['tracks']: metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
