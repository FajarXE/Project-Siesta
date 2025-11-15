# [GANTI FILE: bot/helpers/tidal/metadata.py]

import copy
from datetime import datetime

# --- TAMBAHAN BARU: Impor LOGGER ---
from bot.logger import LOGGER
# --- AKHIR TAMBAHAN ---

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file


async def get_track_metadata(track_id, t_meta, r_id, cover=None, thumbnail=False):
    """
    Args:
        item_id : track id
        t_meta : raw metadata from tidal (pre-fetched)
    Returns:
        metadata: dict
    """

    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = track_id
    metadata['copyright'] = t_meta['copyright']
    metadata['albumartist'] = t_meta['artist']['name']
    metadata['artist'] = get_artists_name(t_meta)
    metadata['album'] = t_meta['album']['title']
    metadata['isrc'] = t_meta['isrc']

    metadata['title'] = t_meta['title']
    if t_meta['version']:
        metadata['title'] += f' ({t_meta["version"]})'

    metadata['title'] = metadata['title'].replace('/', ' ')

    metadata['duration'] = t_meta['duration']
    metadata['explicit'] = t_meta['explicit']
    metadata['tracknumber'] = t_meta['trackNumber']

    parsed_date = datetime.strptime(t_meta['streamStartDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
    metadata['release_date'] = str(parsed_date.date()) 
    
    if t_meta.get('album') and t_meta['album'].get('releaseDate'):
         metadata['date'] = t_meta['album']['releaseDate'].split('-')[0] 
    else:
         metadata['date'] = str(parsed_date.year) 

    metadata['provider'] = 'Tidal'
    metadata['type'] = 'track'

    # --- MODIFIKASI: Ambil Genre, Disk, dan Composer HANYA dari t_meta ---
    if t_meta.get('genres'):
        metadata['genre'] = ', '.join([g['name'] for g in t_meta['genres']])
    elif t_meta.get('genre'): # Fallback
        metadata['genre'] = t_meta['genre']

    metadata['volume'] = t_meta.get('volumeNumber') 
    if t_meta.get('album') and t_meta['album'].get('numberOfVolumes'):
        metadata['totalvolume'] = t_meta['album']['numberOfVolumes']

    # Ambil composer dari data track utama jika ada
    if t_meta.get('composers'):
        metadata['composer'] = ', '.join([c['name'] for c in t_meta['composers']])
    # --- AKHIR MODIFIKASI (Panggilan 'client.get_track_contributors' dihapus) ---

    metadata['cover'] = cover if cover else await get_cover(t_meta['album'].get('cover'), metadata)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(t_meta['album'].get('cover'), metadata, True)

    return metadata


async def get_album_metadata(album_id, a_meta, t_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta['artist']['name']
    metadata['upc'] = a_meta['upc']
    metadata['title'] = a_meta['title']
    if a_meta['version']:
        metadata['title'] += f' ({a_meta["version"]})'
    metadata['album'] = a_meta['title']
    metadata['artist'] = get_artists_name(a_meta)
    
    if a_meta.get('releaseDate'):
        metadata['release_date'] = a_meta['releaseDate'] 
        metadata['date'] = a_meta['releaseDate'].split('-')[0] 
    
    metadata['totaltracks'] = a_meta['numberOfTracks']
    metadata['duration'] = a_meta['duration']
    metadata['copyright'] = a_meta['copyright']
    metadata['explicit'] = a_meta['explicit']
    metadata['totalvolume'] = a_meta['numberOfVolumes']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'album'

    metadata['cover'] = await get_cover(a_meta.get('cover'), metadata)
    metadata['thumbnail'] = await get_cover(a_meta.get('cover'), metadata, True)


    # --- MODIFIKASI BESAR: Buat "stub" (rangka) ---
    metadata['tracks'] = []
    for track in t_meta['items']:
        stub_meta = {
            'itemid': track['id'],
            'albumartist': metadata['albumartist'],
            'album': metadata['album'],
            'cover': metadata['cover'], 
            'thumbnail': metadata['thumbnail'], 
            'provider': 'Tidal',
            'title': track['title'].replace('/', ' ') if track.get('title') else 'Unknown Title',
            'artist': get_artists_name(track),
            'tracknumber': track.get('trackNumber', 1)
        }
        metadata['tracks'].append(stub_meta)
    # --- AKHIR MODIFIKASI BESAR ---
    
    return metadata

# --- TAMBAHAN BARU UNTUK PLAYLIST ---
async def get_playlist_metadata(playlist_id, p_meta, t_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = playlist_id
    metadata['albumartist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['artist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['title'] = p_meta['title']
    metadata['album'] = p_meta['title'] 
    
    try:
        parsed_date = datetime.strptime(p_meta['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        metadata['release_date'] = str(parsed_date.date())
        metadata['date'] = str(parsed_date.year)
    except (ValueError, KeyError):
        metadata['date'] = '2000' 
        metadata['release_date'] = '2000-01-01' 

    metadata['totaltracks'] = p_meta['numberOfTracks']
    metadata['duration'] = p_meta['duration']
    metadata['copyright'] = "" 
    metadata['explicit'] = p_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist' 

    metadata['cover'] = await get_cover(p_meta.get('image'), metadata)
    metadata['thumbnail'] = await get_cover(p_meta.get('image'), metadata, True)

    # --- MODIFIKASI BESAR (PLAYLIST): Buat stub ---
    metadata['tracks'] = []
    for item in t_meta['items']:
        if item.get('type') == 'track' and item.get('item'):
            track = item['item']
            stub_meta = {
                'itemid': track['id'],
                'albumartist': track['artist']['name'] if track.get('artist') else 'Various Artists',
                'album': track['album']['title'] if track.get('album') else 'Unknown Album',
                'cover': None, 
                'thumbnail': None,
                'provider': 'Tidal',
                'title': track['title'].replace('/', ' ') if track.get('title') else 'Unknown Title',
                'artist': get_artists_name(track),
                'tracknumber': track.get('trackNumber', 1)
            }
            metadata['tracks'].append(stub_meta)
    
    metadata['totaltracks'] = len(metadata['tracks'])
    # --- AKHIR MODIFIKASI BESAR ---
    
    return metadata
# --- AKHIR TAMBAHAN ---

async def get_artist_metadata(a_meta:dict, r_id):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['artist'] = a_meta['name']
    metadata['title'] = a_meta['name']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'artist'
    metadata['cover'] = await get_cover(a_meta.get('picture'), metadata)
    metadata['thumbnail'] = await get_cover(a_meta.get('picture'), metadata, True)
    return metadata


async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (
            f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/80x80.jpg'
            if thumbnail
            else f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/1400x1400.jpg'
        )
    return await create_cover_file(url, meta, thumbnail)


def get_artists_name(meta:dict):
    artists = []
    if meta.get('artists'): 
        for a in meta['artists']:
            artists.append(a['name'])
    elif meta.get('artist'): 
        artists.append(meta['artist']['name'])
        
    if not artists:
        return "Various Artists" 
        
    return ', '.join([str(artist) for artist in artists])
