# [GANTI FILE: bot/helpers/metadata.py]

import os
import aiohttp
import aiofiles
from datetime import datetime

from mutagen import File
from config import Config
from mutagen import flac, mp4
from mutagen.mp3 import EasyMP3
# --- TAMBAHAN IMPOR WAVE ---
from mutagen.wave import WAVE 
# ---------------------------
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TDRL, ID3 

from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

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
        'release_date': '', 
        'totaltracks': '',
        'quality': '',
        'extension': '',
        'lyrics': '',
        'volume': '',
        'totalvolume': '',
        'genre': '',
        'subgenre': '', 
        'provider': '',
        'tracks': [],
        'albums': [],
        'composer': '', 
        'tempfolder': f'{Config.DOWNLOAD_BASE_DIR}/',
        'filepath': '',
        'folderpath': '',
        'poster_msg': None,
        'type': ''
    }


async def set_metadata(metadata:dict, user_id: int = None): 
    audio_path = metadata['filepath']
    
    # Deteksi file secara otomatis
    try:
        handle = File(audio_path)
    except Exception as e:
        LOGGER.error(f"Mutagen gagal membaca file {audio_path}: {e}")
        return

    if not handle:
        # Fallback manual jika deteksi otomatis gagal (terutama untuk WAV yang salah ekstensi)
        if audio_path.endswith('.wav'):
             try:
                 handle = WAVE(audio_path)
             except: pass
    
    if metadata['duration'] == '':
        try: metadata['duration'] = handle.info.length
        except: pass

    if lyrics_manager and user_id:
        try:
            lyrics_text = await lyrics_manager.fetch_lyrics(metadata, user_id)
            if lyrics_text:
                metadata['lyrics'] = lyrics_text
        except Exception:
            pass

    try:
        # Cek MIME Type untuk routing fungsi yang benar
        mime = getattr(handle, 'mime', [])
        
        if 'audio/x-flac' in mime:
            await set_flac(metadata, handle)
        elif 'audio/mpeg' in mime:
            await set_mp3(metadata, handle)
        elif 'audio/x-m4a' in mime: 
            await set_m4a(metadata, handle)
        # --- TAMBAHAN LOGIKA WAV ---
        elif 'audio/x-wav' in mime or 'audio/wav' in mime or audio_path.lower().endswith('.wav'):
            # Jika handle bukan objek WAVE (misal File() generik), paksa reload sebagai WAVE
            if not isinstance(handle, WAVE):
                try: handle = WAVE(audio_path)
                except: pass
            await set_wav(metadata, handle)
        # ---------------------------
        else:
            LOGGER.warning(f"Format tidak dikenali untuk tagging: {mime} pada {audio_path}")

    except Exception as e:
        LOGGER.error(f"Gagal menulis metadata untuk {audio_path}: {e}")


async def set_flac(data, handle):
    if handle.tags is None:
            handle.add_tags()
    
    handle.tags['TITLE'] = data['title']
    handle.tags['ALBUM'] = data['album']
    handle.tags['ALBUMARTIST'] = data['albumartist']
    handle.tags['ARTIST'] = data['artist']
    handle.tags['COPYRIGHT'] = data['copyright']
    handle.tags['TRACKNUMBER'] = str(data['tracknumber'])
    handle.tags['TRACKTOTAL'] = str(data['totaltracks'])
    
    if data.get('genre'):
        handle.tags['GENRE'] = data['genre']
    if data.get('composer'):
        handle.tags['COMPOSER'] = data['composer']
    
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    
    if disc_num: handle.tags['DISCNUMBER'] = disc_num
    if disc_total: handle.tags['DISCTOTAL'] = disc_total
    
    if data.get('date'): handle.tags['DATE'] = data['date']
    if data.get('release_date'): handle.tags['RELEASETIME'] = data['release_date']
    if data.get('subgenre'): handle.tags['SUBGENRE'] = data['subgenre']
    
    handle.tags['ISRC'] = data['isrc']
    if data.get('lyrics'):
        handle.tags['LYRICS'] = data['lyrics']
    
    if data.get('bit_depth'):
        handle.tags['BPS'] = str(data['bit_depth'])
    if data.get('sample_rate'):
        handle.tags['SAMPLERATE'] = str(int(data['sample_rate'] * 1000))
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle):
    if handle.tags is None:
            handle.add_tags()
    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    track_pos = f"{track_num}/{track_total}" if track_total and track_total != '0' else track_num
        
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    disc_pos = f"{disc_num}/{disc_total}" if disc_total and disc_total != '0' else disc_num
        
    genre_text = data.get('genre') or ''
    composer_text = data.get('composer') or ''

    handle.tags.add(TIT2(encoding=3, text=data['title']))
    handle.tags.add(TALB(encoding=3, text=data['album']))
    handle.tags.add(TOPE(encoding=3, text=data['albumartist']))
    handle.tags.add(TPE1(encoding=3, text=data['artist']))
    handle.tags.add(TCOP(encoding=3, text=data['copyright']))
    handle.tags.add(TRCK(encoding=3, text=track_pos)) 
    if disc_pos: handle.tags.add(TPOS(encoding=3, text=disc_pos)) 
    if genre_text: handle.tags.add(TCON(encoding=3, text=genre_text)) 
    if data.get('date'): handle.tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): handle.tags.add(TDRL(encoding=3, text=data['release_date']))
    if data.get('subgenre'): handle.tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data.get('subgenre')))
    
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'):
        handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if composer_text: handle.tags.add(TCOM(encoding=3, text=composer_text)) 
    
    if data.get('bit_depth'):
        handle.tags.add(TXXX(encoding=3, desc='BPS', text=str(data['bit_depth'])))
    if data.get('sample_rate'):
        handle.tags.add(TXXX(encoding=3, desc='SAMPLERATE', text=str(int(data['sample_rate'] * 1000))))
    
    await savePic(handle, data)
    handle.save()
    return True

# --- FUNGSI BARU: SET WAV (Menggunakan ID3 chunk di dalam WAV) ---
async def set_wav(data, handle):
    # Mutagen WAVE mendukung tag ID3, jadi kita bisa menggunakan kembali logika MP3
    # atau memanggil add_tags() lalu set frame ID3
    try:
        if handle.tags is None:
            handle.add_tags()
        
        # Panggil set_mp3 karena WAVE di mutagen membungkus ID3
        await set_mp3(data, handle)
        return True
    except Exception as e:
        LOGGER.error(f"Gagal set WAV tags: {e}")
        return False
# -----------------------------------------------------------------

async def set_m4a(data, handle):
    if handle.tags is None:
        handle.add_tags()
    handle.tags['\u00a9nam'] = data['title']
    handle.tags['\u00a9alb'] = data['album']
    handle.tags['\u00a9ART'] = data['artist']
    handle.tags['aART'] = data['albumartist']
    
    if data.get('genre'): handle.tags['\u00a9gen'] = data['genre']
    if data.get('composer'): handle.tags['\u00a9wrt'] = data['composer']
    if data.get('date'): handle.tags['\u00a9day'] = data['date']
    handle.tags['\u00a9cpr'] = data['copyright']

    if data.get('subgenre'): 
        handle.tags['----:com.apple.iTunes:SUBGENRE'] = data.get('subgenre').encode('utf-8')
    if data.get('release_date'): 
        handle.tags['----:com.apple.iTunes:RELEASETIME'] = data.get('release_date').encode('utf-8')

    track_number = int(str(data.get('tracknumber') or '0'))
    totaltracks = int(str(data.get('totaltracks') or '0'))
    volume = int(str(data.get('volume') or '0'))
    totalvolume = int(str(data.get('totalvolume') or '0'))

    handle.tags['trkn'] = [(track_number, totaltracks)]
    handle.tags['disk'] = [(volume, totalvolume)]
    
    if data.get('lyrics'):
        handle.tags['\u00a9lyr'] = data['lyrics']

    if data.get('bit_depth'):
        handle.tags['----:com.apple.iTunes:BITS PER SAMPLE'] = str(data['bit_depth']).encode('utf-8')
    if data.get('sample_rate'):
        handle.tags['----:com.apple.iTunes:SAMPLERATE'] = str(int(data['sample_rate'] * 1000)).encode('utf-8')
    
    await savePic(handle, data)
    handle.save()
    return True


async def savePic(handle, metadata):
    album_art = metadata['cover']
    if album_art == './project-siesta.png' or not os.path.exists(album_art):
        return
    try:
        with open(album_art, "rb") as f:
            data = f.read()
    except Exception:
        return

    # Logika untuk berbagai format
    try:
        # FLAC
        if hasattr(handle, 'mime') and 'audio/x-flac' in handle.mime:
            pic = flac.Picture()
            pic.data = data
            pic.mime = u"image/jpeg"
            handle.clear_pictures()
            handle.add_picture(pic)
        
        # MP3 & WAV (WAV menggunakan ID3 APIC juga)
        elif (hasattr(handle, 'mime') and ('audio/mpeg' in handle.mime or 'audio/x-wav' in handle.mime)) or isinstance(handle, WAVE):
            handle.tags.add(APIC(encoding=3, data=data, mime='image/jpeg', type=3, desc=u'Cover'))
        
        # M4A
        elif hasattr(handle, 'mime') and 'audio/x-m4a' in handle.mime:
            pic = mp4.MP4Cover(data)
            handle.tags['covr'] = [pic]
            
    except Exception as e:
        LOGGER.error(f"Gagal menyimpan gambar: {e}")

async def get_audio_extension(path):
    # Update helper ekstensi
    try:
        handle = File(path)
        if 'audio/x-m4a' in handle.mime: return 'm4a'
        elif 'audio/x-flac' in handle.mime: return 'flac'
        elif 'audio/x-wav' in handle.mime: return 'wav' # Tambah WAV
        else: return 'mp3'
    except:
        return 'mp3' # Default

async def _download_cover_with_headers(url: str, destination: str):
    if not url: return "No URL provided"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=60) as response:
                if response.status == 200:
                    async with aiofiles.open(destination, 'wb') as f:
                        await f.write(await response.read())
                    return None 
                else:
                    return f"HTTP Status: {response.status}"
    except Exception as e:
        return str(e)

async def create_cover_file(url:str, meta:dict, thumbnail=False): 
    filename = f"{meta['itemid']}-thumb.jpg" if thumbnail else f"{meta['itemid']}.jpg"
    cover = meta['tempfolder'] + filename
    if not os.path.exists(cover):
        err = await _download_cover_with_headers(url, cover) 
        if err: return './project-siesta.png'
    if os.path.exists(cover) and os.path.getsize(cover) > 0:
        return cover
    else:
        return './project-siesta.png'
