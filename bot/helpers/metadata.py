import os

from mutagen import File
from config import Config
from mutagen import flac, mp4
from mutagen.mp3 import EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TEXT # Impor sudah benar

from bot.logger import LOGGER
# MODIFIKASI: Impor dari .utils di level 'helpers'
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
        # --- MODIFIKASI: Menggunakan key yang benar ---
        'disk': '',
        'totaldiscs': '',
        # --- MODIFIKASI SELESAI ---
        'genre': '',
        'provider': '',
        'tracks': [],
        'albums': [],
        'composer': '',
        'songwriter': '',
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
        try:
            metadata['duration'] = handle.info.length
        except Exception as e:
            LOGGER.warning(f"Gagal mendapatkan durasi dari file: {e}")
            metadata['duration'] = 0 # default

    if 'audio/x-flac' in handle.mime:
        await set_flac(metadata, handle)
    elif 'audio/mpeg' in handle.mime:
        await set_mp3(metadata, handle)
    elif 'audio/x-m4a' in handle.mime: 
        await set_m4a(metadata, handle)


async def set_flac(data, handle):
    if handle.tags is None:
            handle.add_tags()
    handle.tags['title'] = data.get('title', '')
    handle.tags['album'] = data.get('album', '')
    handle.tags['albumartist'] = data.get('albumartist', '')
    handle.tags['artist'] = data.get('artist', '')
    handle.tags['copyright'] = data.get('copyright', '')
    handle.tags['tracknumber'] = str(data.get('tracknumber', '1'))
    handle.tags['tracktotal'] = str(data.get('totaltracks', '1'))
    handle.tags['genre'] = data.get('genre', '')
    handle.tags['date'] = data.get('date', '')
    handle.tags['isrc'] = data.get('isrc', '')
    handle.tags['lyrics'] = data.get('lyrics', '')
    
    # --- MODIFIKASI DIMULAI (Menggunakan .get() dan key yang benar) ---
    handle.tags['discnumber'] = str(data.get('disk', '1'))
    handle.tags['disctotal'] = str(data.get('totaldiscs', '1'))
    handle.tags['composer'] = data.get('composer', '')
    handle.tags['songwriter'] = data.get('songwriter', '')
    # --- MODIFIKASI SELESAI ---
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle):
    # ID3
    if handle.tags is None:
            handle.add_tags()
    handle.tags.add(TIT2(encoding=3, text=data.get('title', '')))
    handle.tags.add(TALB(encoding=3, text=data.get('album', '')))
    handle.tags.add(TOPE(encoding=3, text=data.get('albumartist', '')))
    handle.tags.add(TPE1(encoding=3, text=data.get('artist', '')))
    handle.tags.add(TCOP(encoding=3, text=data.get('copyright', '')))
    
    # --- MODIFIKASI DIMULAI (Perbaikan Tag Track & Disk dengan key yang benar) ---
    track_text = str(data.get('tracknumber', '1'))
    if data.get('totaltracks') and str(data.get('totaltracks')) not in ['0', '1']:
        track_text = f"{data.get('tracknumber', '1')}/{data.get('totaltracks')}"
    handle.tags.add(TRCK(encoding=3, text=track_text))
    
    disk_text = str(data.get('disk', '1'))
    if data.get('totaldiscs') and str(data.get('totaldiscs')) not in ['0', '1']:
        disk_text = f"{data.get('disk', '1')}/{data.get('totaldiscs')}"
    handle.tags.add(TPOS(encoding=3, text=disk_text))
    # --- MODIFIKASI SELESAI ---
    
    handle.tags.add(TCON(encoding=3, text=data.get('genre', '')))
    handle.tags.add(TDRC(encoding=3, text=data.get('date', '')))
    handle.tags.add(TSRC(encoding=3, text=data.get('isrc', '')))
    handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data.get('lyrics', '')))
    
    handle.tags.add(TCOM(encoding=3, text=data.get('composer', ''))) 
    handle.tags.add(TEXT(encoding=3, text=data.get('songwriter', '')))
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_m4a(data, handle):
    if handle.tags is None:
        handle.add_tags()
    handle.tags['\u00a9nam'] = data.get('title', '')
    handle.tags['\u00a9alb'] = data.get('album', '')
    handle.tags['\u00a9ART'] = data.get('artist', '')
    handle.tags['aART'] = data.get('albumartist', '')
    handle.tags['\u00a9day'] = data.get('date', '')
    handle.tags['\u00a9gen'] = data.get('genre', '')
    handle.tags['\u00a9cpr'] = data.get('copyright', '')

    # --- MODIFIKASI DIMULAI (Menggunakan .get() dan key yang benar) ---
    track_number = int(data.get('tracknumber', '1'))
    totaltracks = int(data.get('totaltracks', '1'))
    handle.tags['trkn'] = [(track_number, totaltracks)]
    
    volume = int(data.get('disk', '1'))
    totalvolume = int(data.get('totaldiscs', '1'))
    handle.tags['disk'] = [(volume, totalvolume)]
    
    handle.tags['\u00a9wrt'] = data.get('composer', '') 
    handle.tags['\u00a9lyr'] = data.get('lyrics', '')   
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
