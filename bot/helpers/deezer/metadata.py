import copy
from datetime import datetime

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .dzapi import deezerapi
from bot.logger import LOGGER


async def process_track_metadata(track_id, r_id, cover=None, 
    thumbnail=None, total_tracks=None, album_genre=None, total_disks=None): # <-- MODIFIKASI: Menambahkan genre/disk
    metadata = copy.deepcopy(base_meta)

    raw_meta = await deezerapi.get_track(track_id)
    raw_meta=raw_meta['DATA']
    t_meta = raw_meta.get('FALLBACK', raw_meta)
    
    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = track_id
    metadata['copyright'] = t_meta.get('COPYRIGHT', '')
    metadata['albumartist'] = t_meta['ART_NAME']
    metadata['artist'] = get_artists_name(t_meta)
    metadata['album'] = t_meta['ALB_TITLE']
    metadata['isrc'] = t_meta['ISRC']

    metadata['title'] = t_meta['SNG_TITLE']
    if t_meta.get('VERSION'):
        metadata['title'] += f' ({t_meta["VERSION"]})'

    metadata['title'] = metadata['title'].replace('/', ' ')

    metadata['duration'] = t_meta['DURATION']
    
    try:
        explicit_status = t_meta.get('EXPLICIT_TRACK_CONTENT', {}).get('EXPLICIT_LYRICS_STATUS', 0)
        metadata['explicit'] = True if explicit_status == 1 else False
    except Exception:
        metadata['explicit'] = False 
    
    metadata['tracknumber'] = t_meta['TRACK_NUMBER']

    if total_tracks:
        metadata['totaltracks'] = total_tracks

    metadata['date'] = t_meta.get('PHYSICAL_RELEASE_DATE', '')

    metadata['provider'] = 'Deezer'
    metadata['type'] = 'track'
    
    # --- MODIFIKASI DIMULAI (Menambahkan Genre, Disk, Composer) ---
    if album_genre:
        metadata['genre'] = album_genre
    elif t_meta.get('GENRE_NAME'):
         metadata['genre'] = t_meta['GENRE_NAME']
         
    metadata['volume'] = str(t_meta.get('DISK_NUMBER', '1')) # Nomor Disk
    
    if total_disks:
        metadata['totalvolume'] = str(total_disks) # Total Disk dari Album
    
    # Menambahkan Pengarang Lagu (Composer/Writer)
    if t_meta.get('CONTRIBUTORS'):
        composers = []
        # Cari Composer (1), Writer (4), atau Lyricist (5)
        for contributor in t_meta['CONTRIBUTORS']:
            # Beberapa role ID mungkin integer, kita pastikan keduanya string
            role_id = str(contributor.get('ROLE_ID'))
            if role_id in ['1', '4', '5']: 
                composers.append(contributor.get('ART_NAME'))
        if composers:
            # Hapus duplikat sambil menjaga urutan
            metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))
    # --- MODIFIKASI SELESAI ---

    metadata['cover'] = cover if cover else await get_cover(t_meta['ALB_PICTURE'], metadata)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(t_meta['ALB_PICTURE'], metadata, True)

    metadata['token'] = t_meta['TRACK_TOKEN']
    metadata['token_expiry'] = t_meta['TRACK_TOKEN_EXPIRE']

    metadata['quality'] = await get_quality(t_meta)

    return metadata
            

async def process_album_metadata(album_id:int, a_meta:dict, t_meta:list, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = album_id

    metadata['albumartist'] = a_meta['ART_NAME']
    metadata['upc'] = a_meta['UPC']
    metadata['title'] = a_meta['ALB_TITLE']
    if a_meta.get('VERSION'):
        metadata['title'] += f' ({a_meta['VERSION']})'
    metadata['album'] = a_meta['ALB_TITLE']
    metadata['artist'] = get_artists_name(a_meta)
    metadata['date'] = a_meta['DIGITAL_RELEASE_DATE']
    metadata['totaltracks'] = a_meta['NUMBER_TRACK'] 
    metadata['duration'] = a_meta['DURATION']
    metadata['copyright'] = a_meta['COPYRIGHT']
    metadata['explicit'] = a_meta.get('explicit_lyrics', False)
    
    # --- MODIFIKASI DIMULAI (Menambahkan Genre dan Total Disk) ---
    album_genre_name = ''
    if a_meta.get('genres') and a_meta['genres'].get('data'):
        # Pastikan data tidak kosong
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
            metadata['genre'] = album_genre_name
    
    metadata['totalvolume'] = str(a_meta.get('DISK_COUNT', '1')) # Total Disk
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
            metadata['totalvolume'] # <-- Meneruskan Total Disk
        )
        metadata['tracks'].append(track_meta)

    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
    else:
        metadata['quality'] = "N/A"
    
    return metadata



async def process_playlist_meta(raw_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['title'] = raw_meta['DATA']['TITLE']
    metadata['duration'] = raw_meta['DATA']['DURATION']
    metadata['totaltracks'] = raw_meta['DATA']['NB_SONG'] 
    metadata['itemid'] = raw_meta['DATA']['PLAYLIST_ID']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Deezer'
    metadata['cover'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata, True)
    
    for track in raw_meta['SONGS']['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], 
                r_id,
                total_tracks=metadata['totaltracks'] 
            )
        except:
            continue
        metadata['tracks'].append(track_meta)

    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
    else:
        metadata['quality'] = "N/A"

    return metadata

def get_artists_name(meta:dict):
    artists = []
    if meta.get('ARTISTS'):
        for a in meta['ARTISTS']:
            artists.append(a['ART_NAME'])
    return ', '.join([str(artist) for artist in artists])


async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (
            f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/3000x0-none-100-0-0.png'
            if not thumbnail
            else f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/80x0-none-100-0-0.png'
        )
    return await create_cover_file(url, meta, thumbnail)


async def get_quality(meta:dict):
    format = 'FLAC'
    premium_formats = ['FLAC', 'MP3_320']
    countries = meta.get('AVAILABLE_COUNTRIES', {}).get('STREAM_ADS')
    
    if not countries:
        raise Exception("Deezer : Track not available")
    elif deezerapi.country not in countries:
        raise Exception("Deezer : Track not available in your country")
    else:
        formats_to_check = premium_formats
        while len(formats_to_check) != 0:
            if formats_to_check[0] != format:
                formats_to_check.pop(0)
            else:
                break

        temp_f = None
        for f in formats_to_check:
            # Pastikan kunci filesize ada sebelum mengaksesnya
            if f'FILESIZE_{f}' in meta and meta[f'FILESIZE_{f}'] != '0':
                temp_f = f
                break
        if temp_f is None:
            temp_f = 'MP3_128'
        format = temp_f

        if format not in deezerapi.available_formats:
            raise Exception("Deezer : Format not available by your subscription")

    return format
```eof

---

### 2. File `bot/helpers/metadata.py` (Perbaikan)

Sekarang, kita perbarui file metadata *utama* Anda untuk menambahkan dukungan tag yang hilang (terutama `composer`, `discnumber`, dan `disctotal`) untuk file FLAC dan M4A.

```python:Perbaikan Metadata (Utama):bot/helpers/metadata.py
import os

from mutagen import File
from config import Config
from mutagen import flac, mp4
from mutagen.mp3 import EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM # <-- MODIFIKASI: Menambahkan tag Composer

from bot.logger import LOGGER
from .utils import download_file


metadata = {
        'itemid': '',
        'copyright': '',
        'albumartist': '',
        'cover': '',
        'thumbnail': '',
        'artist': '',
        'upc': '',
        'album': '',
        'isrc': '',
        'title': '',
        'duration': '',
        'explicit': '',
        "tracknumber": '',
        'date': '',
        'totaltracks': '',
        'quality': '',
        'extension': '',
        'lyrics': '',
        'volume': '',
        'totalvolume': '',
        'genre': '',
        'provider': '',
        'tracks': [],
        'albums': [],
        # --- MODIFIKASI: Menambahkan Composer ---
        'composer': '', 
        # --- MODIFIKASI SELESAI ---
        'tempfolder': f'{Config.DOWNLOAD_BASE_DIR}/', # specific folder for each user
        'filepath': '',   # if track, full path to file
        'folderpath': '', # if album/playlist the full path to folder
        'poster_msg': None,  # Pyrogram message of post (if exist)
        'type': ''       # track/album/playlist/artist
    }


async def set_metadata(metadata:dict):
    audio_path = metadata['filepath']

    handle = File(audio_path)

    if metadata['duration'] == '':
        metadata['duration'] = handle.info.length

    if 'audio/x-flac' in handle.mime:
        await set_flac(metadata, handle)
    elif 'audio/mpeg' in handle.mime:
        await set_mp3(metadata, handle)
    elif 'audio/x-m4a' in handle.mime: 
        await set_m4a(metadata, handle)


async def set_flac(data, handle):
    if handle.tags is None:
            handle.add_tags()
    handle.tags['title'] = data['title']
    handle.tags['album'] = data['album']
    handle.tags['albumartist'] = data['albumartist']
    handle.tags['artist'] = data['artist']
    handle.tags['copyright'] = data['copyright']
    handle.tags['tracknumber'] = str(data['tracknumber'])
    handle.tags['tracktotal'] = str(data['totaltracks'])
    handle.tags['genre'] = data['genre']
    handle.tags['date'] = data['date']
    handle.tags['isrc'] = data['isrc']
    handle.tags['lyrics'] = data['lyrics']
    
    # --- MODIFIKASI DIMULAI (Menambahkan Tag FLAC yang Hilang) ---
    handle.tags['discnumber'] = str(data['volume'])
    handle.tags['disctotal'] = str(data['totalvolume'])
    handle.tags['composer'] = data.get('composer', '')
    # --- MODIFIKASI SELESAI ---
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle):
    # ID3
    if handle.tags is None:
            handle.add_tags()
    handle.tags.add(TIT2(encoding=3, text=data['title']))
    handle.tags.add(TALB(encoding=3, text=data['album']))
    handle.tags.add(TOPE(encoding=3, text=data['albumartist']))
    handle.tags.add(TPE1(encoding=3, text=data['artist']))
    handle.tags.add(TCOP(encoding=3, text=data['copyright']))
    handle.tags.add(TRCK(encoding=3, text=str(data['tracknumber'])))
    handle.tags.add(TPOS(encoding=3, text=str(data['volume'])))
    handle.tags.add(TXXX(encoding=3, text=str(data['totaltracks'])))
    handle.tags.add(TCON(encoding=3, text=data['genre']))
    handle.tags.add(TDRC(encoding=3, text=data['date']))
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    
    # --- MODIFIKASI DIMULAI (Menambahkan Tag MP3 yang Hilang) ---
    handle.tags.add(TCOM(encoding=3, text=data.get('composer', ''))) # Composer
    # (Total disk/TPOS sudah ada)
    # --- MODIFIKASI SELESAI ---
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_m4a(data, handle):
    if handle.tags is None:
        handle.add_tags()
    handle.tags['\u00a9nam'] = data['title']
    handle.tags['\u00a9alb'] = data['album']
    handle.tags['\u00a9ART'] = data['artist']
    handle.tags['aART'] = data['albumartist']
    handle.tags['\u00a9day'] = data['date']
    handle.tags['\u00a9gen'] = data['genre']
    handle.tags['\u00a9cpr'] = data['copyright']

    track_number = int(data['tracknumber']) if data['tracknumber'] != '' else 0
    totaltracks = int(data['totaltracks']) if data['totaltracks'] != '' else 0
    handle.tags['trkn'] = [(track_number, totaltracks)]
    volume = int(data['volume']) if data['volume'] != '' else 0
    totalvolume = int(data['totalvolume']) if data['totalvolume'] != '' else 0
    handle.tags['disk'] = [(volume, totalvolume)]
    
    # --- MODIFIKASI DIMULAI (Menambahkan Tag M4A yang Hilang) ---
    handle.tags['\u00a9wrt'] = data.get('composer', '') # ©wrt adalah Composer
    # --- MODIFIKASI SELESAI ---

    await savePic(handle, data)
    handle.save()
    return True


async def savePic(handle, metadata):
    album_art = metadata['cover']

    if album_art == './project-siesta.png' or not os.path.exists(album_art):
        LOGGER.warning(f"Cover art tidak ditemukan di {album_art}, tidak menambahkan gambar.")
        return

    try:
        with open(album_art, "rb") as f:
            data = f.read()
    except Exception as e:
        LOGGER.error(e)
        return

    if 'audio/x-flac' in handle.mime:
        pic = flac.Picture()
        pic.data = data
        pic.mime = u"image/jpeg"
        handle.clear_pictures()
        handle.add_picture(pic)

    if 'audio/mpeg' in handle.mime:
        handle.tags.add(APIC(encoding=3, data=data))

    if 'audio/x-m4a' in handle.mime:
        pic = mp4.MP4Cover(data)
        handle.tags['covr'] = [pic]

    if 'audio/ogg' in handle.mime:
        handle['artwork'] = data



async def get_audio_extension(path):
    handle = File(path)
    
    if 'audio/x-m4a' in handle.mime:
        return 'm4a'
    elif 'audio/x-flac' in handle.mime:
        return 'flac'
    else:
        return 'mp3'


async def create_cover_file(url:dict, meta:dict, thumbnail=False):
    filename = f"{meta['itemid']}-thumb.jpg" if thumbnail else f"{meta['itemid']}.jpg"
    cover = meta['tempfolder'] + filename
    
    if not os.path.exists(cover):
        err = await download_file(url, cover, retries=1, timeout=60) 
        
        if err:
            LOGGER.error(f"Gagal mengunduh cover art: {err}")
            return './project-siesta.png'
            
    if os.path.exists(cover) and os.path.getsize(cover) > 0:
        return cover
    else:
        return './project-siesta.png'
```eof
