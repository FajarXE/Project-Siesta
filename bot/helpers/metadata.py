import os

from mutagen import File
from config import Config
from mutagen import flac, mp4
from mutagen.mp3 import EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM 

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
        'composer': '', 
        'tempfolder': f'{Config.DOWNLOAD_BASE_DIR}/', # specific folder for each user
        'filepath': '',   # if track, full path to file
        'folderpath': '', # if album/playlist the full path to folder
        'poster_msg': None,  # Pyrogram message of post (if exist)
        'type': ''       # track/album/playlist/artist
    }


async def set_metadata(metadata:dict):
    audio_path = metadata['filepath']

    handle = File(audio_path)
    
    # --- TAMBAHAN BARIS DEBUGGING ---
    # Baris ini akan mencetak ke log Anda data apa yang diterima
    LOGGER.info(f"DEBUG METADATA: Menerima Genre='{metadata.get('genre')}' dan Composer='{metadata.get('composer')}' untuk lagu {metadata.get('title')}")
    # --- BATAS TAMBAHAN ---

    if metadata['duration'] == '':
        metadata['duration'] = handle.info.length

    try:
        if 'audio/x-flac' in handle.mime:
            await set_flac(metadata, handle)
        elif 'audio/mpeg' in handle.mime:
            await set_mp3(metadata, handle)
        elif 'audio/x-m4a' in handle.mime: 
            await set_m4a(metadata, handle)
    except Exception as e:
        LOGGER.error(f"Gagal menulis metadata untuk {audio_path}: {e}")


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
    handle.tags['genre'] = data.get('genre') or '' 
    handle.tags['date'] = data['date']
    handle.tags['isrc'] = data['isrc']
    handle.tags['lyrics'] = data['lyrics']
    
    handle.tags['discnumber'] = str(data['volume'])
    handle.tags['disctotal'] = str(data['totalvolume'])
    handle.tags['composer'] = data.get('composer', '')
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle):
    # ID3
    if handle.tags is None:
            handle.add_tags()

    # --- MODIFIKASI DIMULAI (Memperbaiki format tag MP3) ---

    # Menggabungkan nomor track dan total track (Contoh: "1/10")
    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    if track_total and track_total != '0':
        track_pos = f"{track_num}/{track_total}"
    else:
        track_pos = track_num

    # Menggabungkan nomor disk dan total disk (Contoh: "1/2")
    disc_num = str(data.get('volume', ''))
    disc_total = str(data.get('totalvolume', ''))
    if disc_total and disc_total != '0':
        disc_pos = f"{disc_num}/{disc_total}"
    else:
        disc_pos = disc_num

    # Memastikan genre dan composer tidak None (minimal string kosong)
    genre_text = data.get('genre') or ''
    composer_text = data.get('composer') or ''
    
    # Menambahkan tag dengan data yang sudah dibersihkan
    handle.tags.add(TIT2(encoding=3, text=data['title']))
    handle.tags.add(TALB(encoding=3, text=data['album']))
    handle.tags.add(TOPE(encoding=3, text=data['albumartist']))
    handle.tags.add(TPE1(encoding=3, text=data['artist']))
    handle.tags.add(TCOP(encoding=3, text=data['copyright']))
    handle.tags.add(TRCK(encoding=3, text=track_pos)) 
    handle.tags.add(TPOS(encoding=3, text=disc_pos)) 
    handle.tags.add(TCON(encoding=3, text=genre_text)) 
    handle.tags.add(TDRC(encoding=3, text=data['date']))
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    handle.tags.add(TCOM(encoding=3, text=composer_text)) 
    
    # --- MODIFIKASI SELESAI ---
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_m4a(data, handle):
    if handle.tags is None:
        handle.add_tags()
        
    # --- INI ADALAH PERBAIKAN DARI ERROR SEBELUMNYA ---
    handle.tags['\u00a9nam'] = data['title']
    handle.tags['\u00a9alb'] = data['album']  # <-- DIPERBAIKI
    handle.tags['\u00a9ART'] = data['artist'] # <-- DIPERBAIKI
    # --- BATAS PERBAIKAN ---
    
    handle.tags['aART'] = data['albumartist']
    handle.tags['\u00a9day'] = data['date']
    handle.tags['\u00a9gen'] = data.get('genre') or '' 
    handle.tags['\u00a9cpr'] = data['copyright']

    track_number = int(data['tracknumber']) if data['tracknumber'] else 0
    totaltracks = int(data['totaltracks']) if data['totaltracks'] else 0
    handle.tags['trkn'] = [(track_number, totaltracks)]
    
    volume = int(data['volume']) if data['volume'] else 0
    totalvolume = int(data['totalvolume']) if data['totalvolume'] else 0
    handle.tags['disk'] = [(volume, totalvolume)]
    
    handle.tags['\u00a9wrt'] = data.get('composer', '') # ©wrt adalah Composer

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
    
    if 'audio/x-flac' in handle.mime:
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
