# [GANTI FILE: bot/helpers/tidal/metadata.py]

import copy

from datetime import datetime

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

    # title might have '/' in it
    metadata['title'] = metadata['title'].replace('/', ' ')

    metadata['duration'] = t_meta['duration']
    metadata['explicit'] = t_meta['explicit']
    metadata['tracknumber'] = t_meta['trackNumber']

    # --- MODIFIKASI: Ambil Tanggal Rilis dan Tanggal Rekam ---
    parsed_date = datetime.strptime(t_meta['streamStartDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
    metadata['release_date'] = str(parsed_date.date()) # Tanggal rilis trek
    
    # Gunakan tahun rilis album sebagai 'date' (Tahun Rekam) jika ada
    if t_meta.get('album') and t_meta['album'].get('releaseDate'):
         metadata['date'] = t_meta['album']['releaseDate'].split('-')[0] # Ambil tahun saja
    else:
         metadata['date'] = str(parsed_date.year) # Fallback ke tahun rilis trek
    # --- AKHIR MODIFIKASI ---

    metadata['provider'] = 'Tidal'
    metadata['type'] = 'track'

    # --- TAMBAHAN BARU: Ambil Genre, Disk, dan Composer ---
    # 1. Ambil Genre
    if t_meta.get('genres'):
        metadata['genre'] = ', '.join([g['name'] for g in t_meta['genres']])
    elif t_meta.get('genre'): # Fallback
        metadata['genre'] = t_meta['genre']

    # 2. Ambil Info Disk (Volume)
    metadata['volume'] = t_meta.get('volumeNumber') # Gunakan .get() agar aman
    if t_meta.get('album') and t_meta['album'].get('numberOfVolumes'):
        metadata['totalvolume'] = t_meta['album']['numberOfVolumes']

    # 3. Ambil Composer
    if t_meta.get('composers'):
        metadata['composer'] = ', '.join([c['name'] for c in t_meta['composers']])
    # --- AKHIR TAMBAHAN ---

    # reuse albumart if possible
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
    
    # --- MODIFIKASI: Pisahkan Tanggal Rilis dan Tahun Rekam ---
    if a_meta.get('releaseDate'):
        metadata['release_date'] = a_meta['releaseDate'] # Tanggal rilis lengkap
        metadata['date'] = a_meta['releaseDate'].split('-')[0] # Tahun rilis
    # --- AKHIR MODIFIKASI ---
    
    metadata['totaltracks'] = a_meta['numberOfTracks']
    metadata['duration'] = a_meta['duration']
    metadata['copyright'] = a_meta['copyright']
    metadata['explicit'] = a_meta['explicit']
    metadata['totalvolume'] = a_meta['numberOfVolumes']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'album'

    metadata['cover'] = await get_cover(a_meta.get('cover'), metadata)
    metadata['thumbnail'] = await get_cover(a_meta.get('cover'), metadata, True)


    # --- MODIFIKASI BESAR: Jangan panggil get_track_metadata ---
    # Alih-alih membuat metadata lengkap (tapi tidak lengkap),
    # kita hanya membuat "stub" (rangka) minimalis.
    # start_track akan dipaksa untuk mengambil metadata lengkap.
    metadata['tracks'] = []
    for track in t_meta['items']:
        stub_meta = {
            'itemid': track['id'],
            'albumartist': metadata['albumartist'],
            'album': metadata['album'],
            'cover': metadata['cover'],
            'thumbnail': metadata['thumbnail'],
            'provider': 'Tidal',
            # Info ini penting untuk nama file di start_track
            'title': track['title'].replace('/', ' ') if track.get('title') else 'Unknown Title',
            'artist': get_artists_name(track),
            'tracknumber': track.get('trackNumber', 1)
        }
        metadata['tracks'].append(stub_meta)
    # --- AKHIR MODIFIKASI BESAR ---
    
    return metadata

# --- TAMBAHAN BARU UNTUK PLAYLIST ---
async def get_playlist_metadata(playlist_id, p_meta, t_meta, r_id):
    """
    Args:
        playlist_id : playlist id (UUID)
        p_meta : raw metadata from tidal for playlist
        t_meta : raw metadata from tidal for playlist items (tracks)
    Returns:
        metadata: dict
    """
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = playlist_id
    metadata['albumartist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['artist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['title'] = p_meta['title']
    metadata['album'] = p_meta['title'] # Gunakan judul playlist sebagai nama folder album
    
    try:
        parsed_date = datetime.strptime(p_meta['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        metadata['release_date'] = str(parsed_date.date())
        metadata['date'] = str(parsed_date.year)
    except (ValueError, KeyError):
        metadata['date'] = '2000' # Fallback date year
        metadata['release_date'] = '2000-01-01' # Fallback date

    metadata['totaltracks'] = p_meta['numberOfTracks']
    metadata['duration'] = p_meta['duration']
    metadata['copyright'] = "" # Playlist tidak memiliki info copyright
    metadata['explicit'] = p_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist' # Set tipe sebagai playlist

    metadata['cover'] = await get_cover(p_meta.get('image'), metadata)
    metadata['thumbnail'] = await get_cover(p_meta.get('image'), metadata, True)

    # --- MODIFIKASI BESAR (PLAYLIST): Buat stub, jangan panggil get_track_metadata ---
    metadata['tracks'] = []
    for item in t_meta['items']:
        if item.get('type') == 'track' and item.get('item'):
            track = item['item']
            # Buat stub minimalis. start_track AKAN mengambil metadata lengkap
            stub_meta = {
                'itemid': track['id'],
                'albumartist': track['artist']['name'] if track.get('artist') else 'Various Artists',
                'album': track['album']['title'] if track.get('album') else 'Unknown Album',
                'cover': None, # Biarkan start_track yang mencari cover aslinya
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
    
    # --- PERBAIKAN: Gunakan a_meta.get('picture') ---
    metadata['cover'] = await get_cover(a_meta.get('picture'), metadata)
    metadata['thumbnail'] = await get_cover(a_meta.get('picture'), metadata, True)
    # --- AKHIR PERBAIKAN ---
    return metadata


async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (
            f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/80x80.jpg'
            if thumbnail
            else f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/1280x1280.jpg'
        )
    return await create_cover_file(url, meta, thumbnail)


def get_artists_name(meta:dict):
    artists = []
    if meta.get('artists'): # Periksa jika 'artists' ada
        for a in meta['artists']:
            artists.append(a['name'])
    elif meta.get('artist'): # Fallback untuk beberapa objek (seperti 'track' sederhana)
        artists.append(meta['artist']['name'])
        
    return ', '.join([str(artist) for artist in artists])
