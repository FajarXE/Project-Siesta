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
    metadata['volume'] = t_meta['volumeNumber']
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


    metadata['tracks'] = []
    for track in t_meta['items']:
        track_meta = await get_track_metadata(track['id'], track, r_id, metadata['cover'], metadata['thumbnail'])
        
        # --- MODIFIKASI: Salin data level album ke setiap trek ---
        # Ini memastikan trek memiliki info 'totalvolume' bahkan jika dipanggil dari album
        if 'totalvolume' in metadata:
            track_meta['totalvolume'] = metadata['totalvolume']
        # 'composer' dan 'genre' biasanya per-trek, jadi kita biarkan apa adanya dari 'get_track_metadata'
        # --- AKHIR MODIFIKASI ---
        
        metadata['tracks'].append(track_meta)
    
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
    # Gunakan pembuat playlist sebagai 'artist', fallback ke 'Various Artists'
    metadata['albumartist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['artist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['title'] = p_meta['title']
    metadata['album'] = p_meta['title'] # Gunakan judul playlist sebagai nama folder album
    
    # Coba ambil tanggal dari format 'created'
    try:
        parsed_date = datetime.strptime(p_meta['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        # --- MODIFIKASI: Pisahkan Tanggal Rilis dan Tahun Rekam ---
        metadata['release_date'] = str(parsed_date.date())
        metadata['date'] = str(parsed_date.year)
        # --- AKHIR MODIFIKASI ---
    except (ValueError, KeyError):
        metadata['date'] = '2000' # Fallback date year
        metadata['release_date'] = '2000-01-01' # Fallback date

    metadata['totaltracks'] = p_meta['numberOfTracks']
    metadata['duration'] = p_meta['duration']
    
    # --- PERBAIKAN: Ubah None menjadi string kosong ---
    metadata['copyright'] = "" # Playlist tidak memiliki info copyright
    # --- PERBAIKAN SELESAI ---
    
    metadata['explicit'] = p_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist' # Set tipe sebagai playlist

    # Gunakan 'image' (UUID) untuk cover playlist
    metadata['cover'] = await get_cover(p_meta.get('image'), metadata)
    metadata['thumbnail'] = await get_cover(p_meta.get('image'), metadata, True)

    metadata['tracks'] = []
    # Loop melalui 'items' dari data tracks
    for item in t_meta['items']:
        # Pastikan item adalah track dan memiliki data
        if item.get('type') == 'track' and item.get('item'):
            track = item['item']
            # Panggil get_track_metadata untuk setiap track
            # Lewatkan cover=None agar setiap track mendapatkan cover album aslinya
            track_meta = await get_track_metadata(
                track['id'], 
                track,  # Ini adalah data track lengkap
                r_id, 
                cover=None, 
                thumbnail=False
            )
            metadata['tracks'].append(track_meta)
    
    # Perbarui jumlah total track berdasarkan track yang valid ditemukan
    metadata['totaltracks'] = len(metadata['tracks'])
    
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
            else f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/1280x1280.jpg'
        )
    return await create_cover_file(url, meta, thumbnail)


def get_artists_name(meta:dict):
    artists = []
    for a in meta['artists']:
        artists.append(a['name'])
    return ', '.join([str(artist) for artist in artists])
