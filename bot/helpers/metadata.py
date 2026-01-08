# [GANTI FILE: bot/helpers/metadata.py]

import os
import aiohttp
import aiofiles
from datetime import datetime

from mutagen import File
from mutagen.wave import WAVE, Wave_write
from mutagen.mp4 import MP4, MP4Cover, MP4Tags
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3, EasyMP3
from config import Config

# Import ID3 frames untuk MP3 & WAV
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TDRL, TLEN, TPE2

from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

# --- FUNGSI HELPER: PARSE DURASI ---
def parse_duration_to_ms(raw):
    """
    Mengubah berbagai format ("02:51", "171.5", 171500) menjadi integer Milidetik.
    """
    if not raw:
        return 0
    try:
        s = str(raw).strip()
        if ':' in s:
            parts = s.split(':')
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + float(part)
            return int(seconds * 1000)
        
        val = float(s)
        if val < 30000: 
            return int(val * 1000)
        else:
            return int(val)
    except Exception:
        return 0
# ----------------------------------------

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
    
    try:
        handle = File(audio_path)
        if not handle:
            LOGGER.error(f"Mutagen gagal membaca file: {audio_path}")
            return
    except Exception as e:
        LOGGER.error(f"Error membuka file {audio_path}: {e}")
        return
    
    # 1. FIX DURASI (Global)
    current_dur = metadata.get('duration', 0)
    if not current_dur:
        try:
            if hasattr(handle, 'info') and hasattr(handle.info, 'length'):
                current_dur = handle.info.length 
        except:
            pass

    dur_ms = parse_duration_to_ms(current_dur)
    if dur_ms > 0:
        metadata['duration'] = int(dur_ms / 1000) # Update ke detik untuk Telegram
    else:
        metadata['duration'] = 0

    # 2. AMBIL LIRIK
    if lyrics_manager and user_id:
        try:
            lyrics_text = await lyrics_manager.fetch_lyrics(metadata, user_id)
            if lyrics_text:
                metadata['lyrics'] = lyrics_text
                LOGGER.info(f"Lirik ditemukan dan ditambahkan untuk: {metadata['title']}")
            else:
                LOGGER.info(f"Tidak ada lirik ditemukan untuk: {metadata['title']}")
        except Exception as e:
            LOGGER.error(f"Error fetching lyrics inside metadata: {e}")

    # 3. ROUTING BERDASARKAN TIPE OBJEK (Lebih Akurat daripada MIME)
    try:
        # Cek tipe class instance
        if isinstance(handle, FLAC):
            LOGGER.info(f"Format FLAC terdeteksi: {audio_path}")
            await set_flac(metadata, handle, dur_ms)
            
        elif isinstance(handle, MP4): # Menangani M4A, MP4, M4B
            LOGGER.info(f"Format MP4/M4A terdeteksi: {audio_path}")
            await set_m4a(metadata, handle)
            
        elif isinstance(handle, WAVE) or isinstance(handle, Wave_write):
            LOGGER.info(f"Format WAV terdeteksi: {audio_path}")
            await set_wav(metadata, handle, dur_ms)
            
        elif isinstance(handle, MP3) or isinstance(handle, EasyMP3) or audio_path.lower().endswith('.mp3'):
            LOGGER.info(f"Format MP3 terdeteksi: {audio_path}")
            await set_mp3(metadata, handle, dur_ms)
            
        else:
            # Coba deteksi manual via ekstensi jika instance check gagal
            ext = os.path.splitext(audio_path)[1].lower()
            LOGGER.warning(f"Tipe Mutagen tidak spesifik ({type(handle)}). Mencoba via ekstensi: {ext}")
            
            if ext in ['.m4a', '.mp4']:
                await set_m4a(metadata, handle)
            elif ext in ['.wav']:
                await set_wav(metadata, handle, dur_ms)
            elif ext in ['.flac']:
                await set_flac(metadata, handle, dur_ms)
            elif ext in ['.mp3']:
                await set_mp3(metadata, handle, dur_ms)
            else:
                LOGGER.error(f"Format file tidak didukung untuk tagging: {audio_path}")
            
    except Exception as e:
        LOGGER.error(f"Gagal menulis metadata untuk {audio_path}: {e}")


async def set_flac(data, handle, dur_ms=0):
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
    
    if disc_num:
        handle.tags['DISCNUMBER'] = disc_num
    if disc_total:
        handle.tags['DISCTOTAL'] = disc_total
    
    if data.get('date'): 
        handle.tags['DATE'] = data['date']
    
    if data.get('release_date'): 
        handle.tags['RELEASETIME'] = data['release_date']

    if data.get('subgenre'): 
        handle.tags['SUBGENRE'] = data['subgenre']
    
    handle.tags['ISRC'] = data['isrc']
    if data.get('lyrics'):
        handle.tags['LYRICS'] = data['lyrics']
    
    if data.get('bit_depth'):
        handle.tags['BPS'] = str(data['bit_depth'])
    if data.get('sample_rate'):
        handle.tags['SAMPLERATE'] = str(int(data['sample_rate'] * 1000))
    
    # Simpan Cover
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle, dur_ms=0):
    if handle.tags is None:
            handle.add_tags()
    
    tags = handle.tags
    
    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    track_pos = f"{track_num}/{track_total}" if track_total and track_total != '0' else track_num
        
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    disc_pos = f"{disc_num}/{disc_total}" if disc_total and disc_total != '0' else disc_num
        
    genre_text = data.get('genre') or ''
    composer_text = data.get('composer') or ''

    tags.add(TIT2(encoding=3, text=data['title']))
    tags.add(TALB(encoding=3, text=data['album']))
    tags.add(TPE2(encoding=3, text=data['albumartist']))
    tags.add(TOPE(encoding=3, text=data['albumartist'])) 
    tags.add(TPE1(encoding=3, text=data['artist']))
    tags.add(TCOP(encoding=3, text=data['copyright']))
    tags.add(TRCK(encoding=3, text=track_pos)) 
    
    if disc_pos: tags.add(TPOS(encoding=3, text=disc_pos)) 
    if genre_text: tags.add(TCON(encoding=3, text=genre_text)) 
    
    if data.get('date'): tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): tags.add(TDRL(encoding=3, text=data['release_date']))

    if data.get('subgenre'): 
        tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data.get('subgenre')))
    
    tags.add(TSRC(encoding=3, text=data['isrc']))
    
    if data.get('lyrics'):
        tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if composer_text: 
        tags.add(TCOM(encoding=3, text=composer_text)) 
    
    if dur_ms > 0:
         tags.add(TLEN(encoding=3, text=str(dur_ms)))

    if data.get('bit_depth'):
        tags.add(TXXX(encoding=3, desc='BPS', text=str(data['bit_depth'])))
    if data.get('sample_rate'):
        tags.add(TXXX(encoding=3, desc='SAMPLERATE', text=str(int(data['sample_rate'] * 1000))))
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_wav(data, handle, dur_ms=0):
    # Re-init sebagai WAVE agar properti tags ID3 muncul
    try:
        # Jika handle bukan instance WAVE yang benar, load ulang
        if not isinstance(handle, WAVE) and not isinstance(handle, Wave_write):
            handle = WAVE(data['filepath'])
    except:
        pass

    if handle.tags is None:
        handle.add_tags()
    
    tags = handle.tags

    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    track_pos = f"{track_num}/{track_total}" if track_total and track_total != '0' else track_num
        
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    disc_pos = f"{disc_num}/{disc_total}" if disc_total and disc_total != '0' else disc_num

    tags.add(TIT2(encoding=3, text=data['title']))
    tags.add(TALB(encoding=3, text=data['album']))
    tags.add(TPE2(encoding=3, text=data['albumartist']))
    tags.add(TOPE(encoding=3, text=data['albumartist']))
    tags.add(TPE1(encoding=3, text=data['artist']))
    tags.add(TCOP(encoding=3, text=data['copyright']))
    tags.add(TRCK(encoding=3, text=track_pos)) 
    
    if disc_pos: tags.add(TPOS(encoding=3, text=disc_pos)) 
    if data.get('genre'): tags.add(TCON(encoding=3, text=data.get('genre'))) 
    
    if data.get('date'): tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): tags.add(TDRL(encoding=3, text=data['release_date']))

    if data.get('subgenre'): 
        tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data.get('subgenre')))
    
    tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'):
        tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if data.get('composer'): 
        tags.add(TCOM(encoding=3, text=data['composer'])) 

    if dur_ms > 0:
         tags.add(TLEN(encoding=3, text=str(dur_ms)))

    await savePic(handle, data)
    handle.save()
    return True

async def set_m4a(data, handle):
    # Pastikan tags ada
    if handle.tags is None:
        handle.add_tags()
    
    # M4A menggunakan Dictionary, BUKAN .add()
    tags = handle.tags
    
    tags['\u00a9nam'] = data['title']
    tags['\u00a9alb'] = data['album']
    tags['\u00a9ART'] = data['artist']
    tags['aART'] = data['albumartist']
    
    if data.get('genre'):
        tags['\u00a9gen'] = data['genre']
    if data.get('composer'):
        tags['\u00a9wrt'] = data['composer']
    
    track_number = int(data.get('tracknumber') or 0)
    totaltracks = int(data.get('totaltracks') or 0)
    tags['trkn'] = [(track_number, totaltracks)]

    volume = int(data.get('volume') or 0)
    totalvolume = int(data.get('totalvolume') or 0)
    tags['disk'] = [(volume, totalvolume)]
    
    if data.get('date'): 
        tags['\u00a9day'] = data['date']
    
    tags['\u00a9cpr'] = data['copyright']

    if data.get('subgenre'): 
        tags['----:com.apple.iTunes:SUBGENRE'] = data.get('subgenre').encode('utf-8')
        
    if data.get('release_date'): 
        tags['----:com.apple.iTunes:RELEASETIME'] = data.get('release_date').encode('utf-8')
    
    if data.get('lyrics'):
        tags['\u00a9lyr'] = data['lyrics']

    if data.get('bit_depth'):
        tags['----:com.apple.iTunes:BITS PER SAMPLE'] = str(data['bit_depth']).encode('utf-8')
    if data.get('sample_rate'):
        tags['----:com.apple.iTunes:SAMPLERATE'] = str(int(data['sample_rate'] * 1000)).encode('utf-8')
    
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
    except Exception as e:
        LOGGER.error(e)
        return
    
    # Deteksi Tipe Handle untuk Cover Art
    
    # 1. FLAC
    if isinstance(handle, FLAC):
        pic = Picture()
        pic.data = data
        pic.mime = u"image/jpeg"
        handle.clear_pictures()
        handle.add_picture(pic)
        
    # 2. MP3 / WAV (ID3 Tags)
    elif isinstance(handle, MP3) or isinstance(handle, WAVE) or isinstance(handle, EasyMP3):
        # ID3 menggunakan 'APIC'
        if handle.tags is None: handle.add_tags()
        handle.tags.delall("APIC")
        handle.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=data))
        
    # 3. M4A / MP4
    elif isinstance(handle, MP4):
        # MP4 menggunakan 'covr' list
        pic = MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)
        handle.tags['covr'] = [pic]
        
    # 4. Fallback jika instance check gagal (sangat jarang)
    else:
        # Coba cara lama via mime check
        mimes = str(handle.mime) if hasattr(handle, 'mime') else ""
        if 'mp4' in mimes or 'm4a' in mimes:
             pic = MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)
             handle.tags['covr'] = [pic]

async def get_audio_extension(path):
    # Menggunakan Mutagen untuk mendeteksi ekstensi asli
    try:
        handle = File(path)
        if isinstance(handle, MP4): return 'm4a'
        if isinstance(handle, FLAC): return 'flac'
        if isinstance(handle, WAVE): return 'wav'
        if isinstance(handle, MP3): return 'mp3'
    except:
        pass
        
    # Fallback sederhana jika Mutagen gagal
    if path.lower().endswith('.m4a'): return 'm4a'
    if path.lower().endswith('.flac'): return 'flac'
    if path.lower().endswith('.wav'): return 'wav'
    return 'mp3'

async def _download_cover_with_headers(url: str, destination: str):
    if not url: return "No URL provided"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        dir_path = os.path.dirname(destination)
        os.makedirs(dir_path, exist_ok=True)
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=60) as response:
                if response.status == 200:
                    async with aiofiles.open(destination, 'wb') as f:
                        await f.write(await response.read())
                    return None 
                else:
                    return f"HTTP Status: {response.status}"
    except Exception as e:
        return f"Exception: {e}"

async def create_cover_file(url:str, meta:dict, thumbnail=False): 
    filename = f"{meta['itemid']}-thumb.jpg" if thumbnail else f"{meta['itemid']}.jpg"
    cover = meta['tempfolder'] + filename
    if not os.path.exists(cover):
        err = await _download_cover_with_headers(url, cover) 
        if err:
            LOGGER.error(f"Gagal mengunduh cover art: {err}")
            return './project-siesta.png'
    return cover if os.path.exists(cover) and os.path.getsize(cover) > 0 else './project-siesta.png'
