# [GANTI FILE: bot/helpers/tidal/metadata.py]

import copy
import aiohttp
from async_lru import alru_cache
from datetime import datetime

from bot.logger import LOGGER

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file


@alru_cache(maxsize=128)
async def search_itunes_cover(artist_name: str, album_name: str) -> str | None:
    """
    Mencari cover art resolusi tinggi di iTunes API.
    Hasilnya di-cache dalam memori.
    """
    if not artist_name or not album_name:
        return None
        
    LOGGER.info(f"Mencari cover iTunes untuk: {artist_name} - {album_name}")
    search_term = f"{artist_name} {album_name}"
    params = {'term': search_term, 'entity': 'album', 'limit': 1, 'media': 'music'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://itunes.apple.com/search", params=params, timeout=10) as resp:
                if resp.status != 200:
                    LOGGER.warning(f"iTunes API Gagal: Status {resp.status} untuk {search_term}")
                    return None
                
                data = await resp.json()
                if data['resultCount'] > 0:
                    result = data['results'][0]
                    # Lakukan pemeriksaan dasar untuk memastikan hasilnya relevan
                    if (album_name.lower() in result['collectionName'].lower() and
                        artist_name.lower() in result['artistName'].lower()):
                        
                        # --- MODIFIKASI: Minta 3000x3000 ---
                        hi_res_url = result['artworkUrl100'].replace('100x100bb.jpg', '3000x3000bb.jpg')
                        # --- AKHIR MODIFIKASI ---
                        
                        LOGGER.info(f"Ditemukan cover iTunes: {hi_res_url}")
                        return hi_res_url
                    else:
                        LOGGER.warning(f"Hasil iTunes tidak cocok: {result['collectionName']} vs {album_name}")
                        return None
                else:
                    LOGGER.info(f"Tidak ada hasil iTunes untuk: {search_term}")
                    return None
    except Exception as e:
        LOGGER.error(f"Error saat mencari di iTunes: {e}")
        return None


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

    if t_meta.get('genres'):
        metadata['genre'] = ', '.join([g['name'] for g in t_meta['genres']])
    elif t_meta.get('genre'): 
        metadata['genre'] = t_meta['genre']

    metadata['volume'] = t_meta.get('volumeNumber') 
    if t_meta.get('album') and t_meta['album'].get('numberOfVolumes'):
        metadata['totalvolume'] = t_meta['album']['numberOfVolumes']

    if t_meta.get('composers'):
        metadata['composer'] = ', '.join([c['name'] for c in t_meta['composers']])

    # --- MODIFIKASI: Panggil get_cover dengan info artis/album ---
    artist_for_cover = metadata['albumartist']
    album_for_cover = metadata['album']
    tidal_cover_id = t_meta['album'].get('cover')

    metadata['cover'] = cover if cover else await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=False
    )
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=True
    )
    # --- AKHIR MODIFIKASI ---

    return metadata


async def get_album_metadata(album_id, a_meta, t_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta['artist']['name']
    metadata['upc'] = a_meta['upc']
    metadata['title'] = a_meta['title']
    
    album_title = a_meta['title']
    if a_meta['version']:
        metadata['title'] += f' ({a_meta["version"]})'
        album_title += f' ({a_meta["version"]})'
    metadata['album'] = album_title
    
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

    # --- MODIFIKASI: Panggil get_cover dengan info artis/album ---
    artist_for_cover = metadata['albumartist']
    album_for_cover = metadata['album']
    tidal_cover_id = a_meta.get('cover')
    
    metadata['cover'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=False
    )
    metadata['thumbnail'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=True
    )
    # --- AKHIR MODIFIKASI ---

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
    
    return metadata

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

    # --- MODIFIKASI: Panggil get_cover dengan info playlist ---
    artist_for_cover = metadata['artist']
    album_for_cover = metadata['title']
    tidal_cover_id = p_meta.get('image')

    metadata['cover'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=False
    )
    metadata['thumbnail'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=True
    )
    # --- AKHIR MODIFIKASI ---

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
    
    return metadata

async def get_artist_metadata(a_meta:dict, r_id):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['artist'] = a_meta['name']
    metadata['title'] = a_meta['name']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'artist'
    
    # --- MODIFIKASI: Panggil get_cover dengan info artis ---
    artist_for_cover = a_meta['name']
    album_for_cover = a_meta['name'] 
    tidal_cover_id = a_meta.get('picture')

    metadata['cover'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=False
    )
    metadata['thumbnail'] = await get_cover(
        tidal_cover_id, 
        metadata, 
        artist_for_cover, 
        album_for_cover,
        thumbnail=True
    )
    # --- AKHIR MODIFIKASI ---
    return metadata


async def get_cover(cover_id, meta:dict, artist_name: str = None, album_name: str = None, thumbnail=False):
    """
    Mengambil cover.
    Prioritas 1: iTunes (jika artist_name dan album_name diberikan)
    Prioritas 2: Cover ID default Tidal
    """
    
    # Logika thumbnail tetap sama (selalu ambil 80x80 dari Tidal)
    if thumbnail:
        url = None
        if cover_id:
            url = f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/80x80.jpg'
        return await create_cover_file(url, meta, thumbnail)
    
    # --- LOGIKA BARU UNTUK COVER RESOLUSI PENUH ---
    
    # 1. Coba iTunes terlebih dahulu
    itunes_url = None
    if artist_name and album_name:
        itunes_url = await search_itunes_cover(artist_name, album_name)
    
    if itunes_url:
        # Coba unduh dari iTunes
        itunes_cover_path = await create_cover_file(itunes_url, meta, thumbnail)
        
        # Periksa apakah unduhan berhasil (bukan gambar placeholder)
        if itunes_cover_path and 'project-siesta.png' not in itunes_cover_path:
            return itunes_cover_path
        else:
            LOGGER.warning(f"Gagal mengunduh cover iTunes ({itunes_url}), fallback ke Tidal.")
    
    # 2. Fallback ke Tidal jika iTunes gagal atau tidak dicari
    LOGGER.info(f"Menggunakan cover art default Tidal untuk {meta['itemid']}.")
    tidal_url = None
    if cover_id:
        tidal_url = f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/1280x1280.jpg'
    
    return await create_cover_file(tidal_url, meta, thumbnail)
    # --- AKHIR LOGIKA BARU ---


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
