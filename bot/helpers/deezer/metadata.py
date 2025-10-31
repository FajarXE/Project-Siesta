import re
import time

from .api import Deezer
from .utils import get_lrc
from bot.logger import LOGGER
from bot.helpers.metadata import create_cover_file


async def process_track_metadata(t_id, r_id, cover_path, thumb_path, total_tracks, album_genre, total_discs):
    metadata = {}
    t_meta = await Deezer.get_track(t_id)

    metadata['itemid'] = t_meta['SNG_ID']
    metadata['copyright'] = t_meta['COPYRIGHT']
    metadata['albumartist'] = t_meta['ALB_ART_NAME']
    metadata['cover'] = cover_path
    metadata['thumbnail'] = thumb_path
    metadata['artist'] = t_meta['ART_NAME']
    metadata['upc'] = t_meta.get('UPC', '')
    metadata['album'] = t_meta['ALB_TITLE']
    metadata['isrc'] = t_meta['ISRC']
    metadata['title'] = t_meta['SNG_TITLE']
    metadata['duration'] = t_meta['DURATION']
    metadata['explicit'] = 'Yes' if t_meta['EXPLICIT_LYRICS'] else 'No'
    metadata['tracknumber'] = str(t_meta.get('TRACK_NUMBER', '1'))
    metadata['date'] = t_meta.get('PHYSICAL_RELEASE_DATE', '')
    metadata['totaltracks'] = str(total_tracks)
    
    # --- MODIFIKASI DIMULAI (Memperbaiki Genre, Disk, Composer/Songwriter) ---
    
    # 1. Menambahkan Genre
    if album_genre:
        metadata['genre'] = album_genre
    elif t_meta.get('GENRE_NAME'): # Fallback jika genre album tidak ada
         metadata['genre'] = t_meta['GENRE_NAME']
         
    # 2. Memperbaiki Key untuk Nomor Disk
    metadata['disk'] = str(t_meta.get('DISK_NUMBER', '1')) # Menggunakan 'disk'
    
    if total_discs:
        metadata['totaldiscs'] = str(total_discs) # Menggunakan 'totaldiscs'
    
    # 3. Memisahkan Composer dan Songwriter (Pengarang Lagu)
    if t_meta.get('CONTRIBUTORS'):
        composers = []   # Role 1 (Komposer)
        songwriters = [] # Role 4 (Writer) & 5 (Lyricist/Pengarang Lagu)
        
        for contributor in t_meta['CONTRIBUTORS']:
            role_id = str(contributor.get('ROLE_ID')) # Pastikan string
            art_name = contributor.get('ART_NAME')
            
            if role_id == '1':
                composers.append(art_name)
            elif role_id in ['4', '5']: # '4' = Writer, '5' = Lyricist
                songwriters.append(art_name)
                
        if composers:
            # Hapus duplikat
            metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))
        if songwriters:
            # Hapus duplikat
            metadata['songwriter'] = ', '.join(list(dict.fromkeys(songwriters)))
            
    # --- MODIFIKASI SELESAI ---

    metadata['lyrics'] = await get_lrc(metadata['isrc'])
    return metadata


async def process_album_metadata(a_id, r_id):
    metadata = {}
    a_meta = await Deezer.get_album(a_id)
    t_meta = await Deezer.get_album_tracks(a_id)

    metadata['itemid'] = a_meta['ALB_ID']
    metadata['copyright'] = a_meta.get('COPYRIGHT', '')
    metadata['albumartist'] = a_meta['ART_NAME']
    metadata['artist'] = a_meta['ART_NAME']
    metadata['upc'] = a_meta.get('UPC', '')
    metadata['album'] = a_meta['ALB_TITLE']
    metadata['title'] = a_meta['ALB_TITLE']
    metadata['duration'] = a_meta.get('DURATION', '')
    metadata['explicit'] = 'Yes' if a_meta['EXPLICIT_ALBUM'] else 'No'
    metadata['date'] = a_meta.get('PHYSICAL_RELEASE_DATE', '')
    metadata['totaltracks'] = str(a_meta.get('NUMBER_TRACK', '1'))
    
    # --- MODIFIKASI DIMULAI (Menambahkan Genre dan Total Disk) ---
    album_genre_name = ''
    if a_meta.get('genres') and a_meta['genres'].get('data'):
        # Pastikan data tidak kosong
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
            metadata['genre'] = album_genre_name
    
    metadata['totaldiscs'] = str(a_meta.get('DISK_COUNT', '1')) # Menggunakan 'totaldiscs'
    # --- MODIFIKASI SELESAI ---
    
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'

    metadata['cover'] = await get_cover(a_meta['ALB_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(a_meta['ALB_PICTURE'], metadata, True)
        
    metadata['tracks'] = []
    for track in t_meta['data']:
        track_meta = await process_track_metadata(
            track['SNG_ID'], 
            r_id,
            metadata['cover'], 
            metadata['thumbnail'],
            metadata['totaltracks'],
            album_genre_name, # <-- Meneruskan Genre
            metadata['totaldiscs'] # <-- Meneruskan Total Disk
        )
        metadata['tracks'].append(track_meta)

    return metadata


async def get_cover(pic_id, meta, thumbnail=False):
    url = f"https://e-cdn-images.dzcdn.net/images/cover/{pic_id}/1400x1400-000000-80-0-0.jpg"
    return await create_cover_file(url, meta, thumbnail)
