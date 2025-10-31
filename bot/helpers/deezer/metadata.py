import re
import time

from config import Config
from .dzapi import deezerapi
from .utils import get_lrc # <-- MODIFIKASI: Kembali ke '.' (satu titik)
from bot.logger import LOGGER
from bot.helpers.metadata import create_cover_file

# --- FUNGSI INI SEKARANG SANGAT BERBEDA ---
# Dipanggil oleh handler.py saat mengunduh TRACK TUNGGAL
async def process_track_metadata(t_id, r_id):
    metadata = {}
    try:
        # 1. Ambil data track utama
        t_meta_raw = await deezerapi.get_track(t_id)
        t_meta = t_meta_raw.get('FALLBACK') if 'FALLBACK' in t_meta_raw else t_meta_raw.get('DATA')
        if not t_meta:
            raise Exception("Tidak dapat mengambil data track (mungkin tidak tersedia).")
        
        # 2. Ambil data album (untuk genre, total disk, cover, dll)
        a_meta_raw = await deezerapi.get_album(t_meta['ALB_ID'])
        a_meta = a_meta_raw['DATA']
        t_meta_tracks = a_meta_raw['SONGS'] # List lagu di album

        # 3. Cari data track yang lebih lengkap dari daftar lagu album
        full_track_data = t_meta # Fallback
        for track in t_meta_tracks['data']:
            if str(track['SNG_ID']) == str(t_id):
                full_track_data = track
                break
    except Exception as e:
        LOGGER.error(f"Gagal mengambil metadata gabungan untuk track {t_id}: {e}")
        raise e # Lempar error agar handler bisa menangkapnya

    metadata['itemid'] = full_track_data['SNG_ID']
    metadata['copyright'] = a_meta.get('COPYRIGHT', t_meta.get('COPYRIGHT', ''))
    metadata['albumartist'] = a_meta['ART_NAME']
    
    # Buat path cover
    temp_meta_for_cover = {'itemid': metadata['itemid'], 'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/"}
    metadata['cover'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover)
    metadata['thumbnail'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover, True)
    
    metadata['artist'] = full_track_data['ART_NAME']
    metadata['upc'] = a_meta.get('UPC', '')
    metadata['album'] = a_meta['ALB_TITLE']
    metadata['isrc'] = full_track_data['ISRC']
    metadata['title'] = full_track_data['SNG_TITLE']
    metadata['duration'] = full_track_data['DURATION']
    metadata['explicit'] = 'Yes' if full_track_data.get('EXPLICIT_LYRICS') else 'No'
    metadata['tracknumber'] = str(full_track_data.get('TRACK_NUMBER', '1'))
    metadata['date'] = a_meta.get('PHYSICAL_RELEASE_DATE', '')
    metadata['totaltracks'] = str(a_meta.get('NUMBER_TRACK', '1'))

    # --- PERBAIKAN METADATA (Genre, Disk, Composer) ---
    
    # 1. Genre
    album_genre_name = ''
    if a_meta.get('genres') and a_meta['genres'].get('data'):
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
    metadata['genre'] = album_genre_name

    # 2. Disk
    metadata['disk'] = str(full_track_data.get('DISK_NUMBER', '1'))
    metadata['totaldiscs'] = str(a_meta.get('DISK_COUNT', '1'))

    # 3. Composer/Songwriter (Gunakan data dari get_track)
    if t_meta.get('CONTRIBUTORS'):
        composers, songwriters = [], []
        for c in t_meta['CONTRIBUTORS']:
            role_id = str(c.get('ROLE_ID'))
            art_name = c.get('ART_NAME')
            if role_id == '1': composers.append(art_name)
            elif role_id in ['4', '5']: songwriters.append(art_name)
        if composers: metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))
        if songwriters: metadata['songwriter'] = ', '.join(list(dict.fromkeys(songwriters)))

    # --- AKHIR PERBAIKAN ---
    
    # Tambahkan info token (dibutuhkan oleh handler.py)
    metadata['token'] = t_meta['TRACK_TOKEN']
    metadata['token_expiry'] = t_meta['TRACK_TOKEN_EXPIRE']
    # Tentukan Kualitas (handler.py bergantung pada ini)
    if 'FLAC' in deezerapi.available_formats: metadata['quality'] = 'FLAC'
    elif 'MP3_320' in deezerapi.available_formats: metadata['quality'] = 'MP3_320'
    else: metadata['quality'] = 'MP3_128'
    
    metadata['lyrics'] = await get_lrc(metadata) # <-- MODIFIKASI: Mengirim seluruh dict metadata
    return metadata


# --- FUNGSI INI SEKARANG SANGAT BERBEDA ---
# Dipanggil oleh handler.py saat mengunduh ALBUM
async def process_album_metadata(a_id, a_meta, t_meta, r_id):
    metadata = {}
    
    metadata['itemid'] = a_meta['ALB_ID']
    metadata['copyright'] = a_meta.get('COPYRIGHT', '')
    metadata['albumartist'] = a_meta['ART_NAME']
    metadata['artist'] = a_meta['ART_NAME']
    metadata['upc'] = a_meta.get('UPC', '')
    metadata['album'] = a_meta['ALB_TITLE']
    metadata['title'] = a_meta['ALB_TITLE']
    metadata['duration'] = a_meta.get('DURATION', '')
    metadata['explicit'] = 'Yes' if a_meta.get('EXPLICIT_ALBUM') else 'No'
    metadata['date'] = a_meta.get('PHYSICAL_RELEASE_DATE', '')
    metadata['totaltracks'] = str(a_meta.get('NUMBER_TRACK', '1'))
    
    # --- PERBAIKAN METADATA (Genre, Disk) ---
    album_genre_name = ''
    if a_meta.get('genres') and a_meta['genres'].get('data'):
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
    metadata['genre'] = album_genre_name
    metadata['totaldiscs'] = str(a_meta.get('DISK_COUNT', '1'))
    # --- AKHIR PERBAIKAN ---

    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'

    # Buat path cover
    temp_meta_for_cover = {'itemid': metadata['itemid'], 'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/"}
    metadata['cover'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover)
    metadata['thumbnail'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover, True)
    
    metadata['tracks'] = []
    
    # Tentukan Kualitas (untuk semua lagu)
    quality = 'FLAC' if 'FLAC' in deezerapi.available_formats else 'MP3_320' if 'MP3_320' in deezerapi.available_formats else 'MP3_128'
            
    # Loop ini sekarang melakukan N+1 request (1 untuk album, N untuk setiap track)
    # Ini diperlukan untuk mendapatkan token & composer
    for track in t_meta['data']:
        track_meta = {}
        
        # Ambil data track lengkap (untuk token, composer, dll)
        try:
            t_meta_full_raw = await deezerapi.get_track(track['SNG_ID'])
            t_meta_full = t_meta_full_raw['DATA']
        except Exception as e:
            LOGGER.warning(f"Gagal mengambil metadata (token/composer) untuk track album {track['SNG_ID']}: {e}. Melewatkan.")
            continue # Lewati lagu ini
        
        track_meta['itemid'] = track['SNG_ID']
        track_meta['copyright'] = metadata['copyright']
        track_meta['albumartist'] = metadata['albumartist']
        track_meta['cover'] = metadata['cover']
        track_meta['thumbnail'] = metadata['thumbnail']
        track_meta['artist'] = track['ART_NAME']
        track_meta['upc'] = metadata['upc']
        track_meta['album'] = metadata['album']
        track_meta['isrc'] = track['ISRC']
        track_meta['title'] = track['SNG_TITLE']
        track_meta['duration'] = track['DURATION']
        track_meta['explicit'] = 'Yes' if track.get('EXPLICIT_LYRICS') else 'No'
        track_meta['tracknumber'] = str(track.get('TRACK_NUMBER', '1'))
        track_meta['date'] = metadata['date']
        track_meta['totaltracks'] = metadata['totaltracks']
        
        # --- PERBAIKAN METADATA (per track) ---
        track_meta['genre'] = metadata['genre']
        track_meta['disk'] = str(track.get('DISK_NUMBER', '1'))
        track_meta['totaldiscs'] = metadata['totaldiscs']

        if t_meta_full.get('CONTRIBUTORS'):
            composers, songwriters = [], []
            for c in t_meta_full['CONTRIBUTORS']:
                role_id = str(c.get('ROLE_ID'))
                art_name = c.get('ART_NAME')
                if role_id == '1': composers.append(art_name)
                elif role_id in ['4', '5']: songwriters.append(art_name)
            if composers: track_meta['composer'] = ', '.join(list(dict.fromkeys(composers)))
            if songwriters: track_meta['songwriter'] = ', '.join(list(dict.fromkeys(songwriters)))
        # --- AKHIR PERBAIKAN ---

        # Tambahkan info token & kualitas (dibutuhkan oleh handler.py)
        track_meta['token'] = t_meta_full['TRACK_TOKEN']
        track_meta['token_expiry'] = t_meta_full['TRACK_TOKEN_EXPIRE']
        track_meta['quality'] = quality
    
        track_meta['lyrics'] = await get_lrc(track_meta) # <-- MODIFIKASI: Mengirim seluruh dict metadata
        metadata['tracks'].append(track_meta)

    # Perbarui total tracks HANYA untuk lagu yang berhasil diambil
    metadata['totaltracks'] = str(len(metadata['tracks']))
    return metadata


# --- FUNGSI INI JUGA DITULIS ULANG ---
# Dipanggil oleh handler.py saat mengunduh PLAYLIST
async def process_playlist_meta(raw_data, r_id):
    p_meta = raw_data['DATA']
    t_meta = raw_data['SONGS']
    
    metadata = {}
    metadata['itemid'] = p_meta['PLAYLIST_ID']
    metadata['title'] = p_meta['TITLE']
    metadata['totaltracks'] = str(p_meta.get('NB_SONG', '1'))
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'playlist'

    temp_meta_for_cover = {'itemid': metadata['itemid'], 'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/"}
    metadata['cover'] = await get_cover(p_meta['PICTURE'], temp_meta_for_cover)
    metadata['thumbnail'] = await get_cover(p_meta['PICTURE'], temp_meta_for_cover, True)
    
    metadata['tracks'] = []
    
    # Tentukan Kualitas (untuk semua lagu)
    quality = 'FLAC' if 'FLAC' in deezerapi.available_formats else 'MP3_320' if 'MP3_320' in deezerapi.available_formats else 'MP3_128'
            
    for track in t_meta['data']:
        track_meta = {}
        
        # Ambil data track lengkap (untuk token, composer, dll)
        # DAN data album (untuk cover, genre, dll)
        try:
            t_meta_full_raw = await deezerapi.get_track(track['SNG_ID'])
            t_meta_full = t_meta_full_raw['DATA']
            
            a_meta_raw = await deezerapi.get_album(track['ALB_ID'])
            a_meta = a_meta_raw['DATA']
        except Exception as e:
            LOGGER.warning(f"Gagal mengambil metadata (token/album) untuk track playlist {track['SNG_ID']}: {e}. Melewatkan.")
            continue # Lewati lagu ini

        track_meta['itemid'] = track['SNG_ID']
        track_meta['copyright'] = a_meta.get('COPYRIGHT', '')
        track_meta['albumartist'] = a_meta['ART_NAME']
        
        # Gunakan cover album dari track individual
        track_meta['cover'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover)
        track_meta['thumbnail'] = await get_cover(a_meta['ALB_PICTURE'], temp_meta_for_cover, True)
        
        track_meta['artist'] = track['ART_NAME']
        track_meta['upc'] = a_meta.get('UPC', '')
        track_meta['album'] = track['ALB_TITLE']
        track_meta['isrc'] = track['ISRC']
        track_meta['title'] = track['SNG_TITLE']
        track_meta['duration'] = track['DURATION']
        track_meta['explicit'] = 'Yes' if track.get('EXPLICIT_LYRICS') else 'No'
        track_meta['tracknumber'] = str(track.get('TRACK_NUMBER', '1'))
        track_meta['date'] = a_meta.get('PHYSICAL_RELEASE_DATE', '')
        track_meta['totaltracks'] = str(a_meta.get('NUMBER_TRACK', '1'))

        # --- PERBAIKAN METADATA (per track) ---
        album_genre_name = ''
        if a_meta.get('genres') and a_meta['genres'].get('data'):
            if a_meta['genres']['data']:
                album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
        track_meta['genre'] = album_genre_name
        
        track_meta['disk'] = str(track.get('DISK_NUMBER', '1'))
        track_meta['totaldiscs'] = str(a_m.get('DISK_COUNT', '1'))

        if t_meta_full.get('CONTRIBUTORS'):
            composers, songwriters = [], []
            for c in t_meta_full['CONTRIBUTORS']:
                role_id = str(c.get('ROLE_ID'))
                art_name = c.get('ART_NAME')
                if role_id == '1': composers.append(art_name)
                elif role_id in ['4', '5']: songwriters.append(art_name)
            if composers: track_meta['composer'] = ', '.join(list(dict.fromkeys(composers)))
            if songwriters: track_meta['songwriter'] = ', '.join(list(dict.fromkeys(songwriters)))
        # --- AKHIR PERBAIKAN ---
        
        track_meta['token'] = t_meta_full['TRACK_TOKEN']
        track_meta['token_expiry'] = t_meta_full['TRACK_TOKEN_EXPIRE']
        track_meta['quality'] = quality
    
        track_meta['lyrics'] = await get_lrc(track_meta) # <-- MODIFIKASI: Mengirim seluruh dict metadata
        metadata['tracks'].append(track_meta)
    
    # Perbarui total tracks HANYA untuk lagu yang berhasil diambil
    metadata['totaltracks'] = str(len(metadata['tracks']))
    return metadata

# --- FUNGSI INI TIDAK BERUBAH ---
async def get_cover(pic_id, meta, thumbnail=False):
    url = f"https://e-cdn-images.dzcdn.net/images/cover/{pic_id}/1400x1400-000000-80-0-0.jpg"
    return await create_cover_file(url, meta, thumbnail)
