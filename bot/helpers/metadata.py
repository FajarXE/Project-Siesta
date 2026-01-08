# [GANTI FILE: bot/helpers/metadata.py]

import os
import aiohttp
import aiofiles
from datetime import datetime

# Import spesifik class agar Fallback bekerja
from mutagen import File
from mutagen.wave import WAVE 
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TDRL, TLEN, TPE2

from config import Config
from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

# --- FUNGSI HELPER: PARSE DURASI ---
def parse_duration_to_ms(raw):
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
    audio_path = str(metadata['filepath'])
    
    # --- 1. INISIALISASI MUTAGEN DENGAN FALLBACK YANG AMAN ---
    handle = None
    try:
        # Coba deteksi otomatis
        handle = File(audio_path)
        
        # Jika gagal (None), paksa baca berdasarkan ekstensi file
        if handle is None:
            ext = os.path.splitext(audio_path)[1].lower().strip()
            LOGGER.warning(f"Mutagen auto-detect gagal (None). Mencoba fallback manual untuk: {ext}")
            
            # Fallback Manual
            try:
                if '.wav' in ext:
                    handle = WAVE(audio_path)
                elif '.mp3' in ext:
                    handle = MP3(audio_path)
                elif '.flac' in ext:
                    handle = FLAC(audio_path)
                elif ext in ['.m4a', '.mp4', '.m4b']:
                    handle = MP4(audio_path)
            except Exception as e_fallback:
                LOGGER.error(f"Fallback manual error: {e_fallback}")
                
    except Exception as e:
        LOGGER.error(f"Gagal membuka file {audio_path}: {e}")
        return

    # [PERBAIKAN UTAMA] Gunakan 'is None' karena objek Mutagen kosong bisa bernilai False
    if handle is None:
         LOGGER.error(f"File tidak dikenali formatnya: {audio_path}")
         return
    # -----------------------------------------------
    
    # 2. LOGIKA UTAMA PERBAIKAN DURASI
    current_dur = metadata.get('duration', 0)
    
    if not current_dur:
        try:
            if hasattr(handle, 'info') and hasattr(handle.info, 'length'):
                current_dur = handle.info.length 
        except:
            pass

    dur_ms = parse_duration_to_ms(current_dur)
    
    if dur_ms > 0:
        metadata['duration'] = int(dur_ms / 1000)
    else:
        metadata['duration'] = 0

    # 3. LYRICS HANDLING
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

    # 4. ROUTING KE FUNGSI SPESIFIK BERDASARKAN TIPE OBJEK
    try:
        if isinstance(handle, FLAC):
            LOGGER.info(f"Memanggil set_flac untuk: {audio_path}")
            await set_flac(metadata, handle, dur_ms)
            
        elif isinstance(handle, MP4): 
            LOGGER.info(f"Memanggil set_m4a untuk: {audio_path}")
            await set_m4a(metadata, handle)
            
        elif isinstance(handle, WAVE):
            LOGGER.info(f"Memanggil set_wav untuk: {audio_path}")
            await set_wav(metadata, handle, dur_ms)
            
        elif isinstance(handle, (MP3, EasyMP3)):
            LOGGER.info(f"Memanggil set_mp3 untuk: {audio_path}")
            await set_mp3(metadata, handle, dur_ms)
        
        else:
            # Fallback terakhir jika tipe objek generik
            ext = os.path.splitext(audio_path)[1].lower()
            if ext in ['.m4a', '.mp4']:
                 await set_m4a(metadata, handle)
            else:
                LOGGER.warning(f"Format object {type(handle)} tidak dikenali spesifik, mencoba MP3 fallback.")
                await set_mp3(metadata, handle, dur_ms) 
            
    except Exception as e:
        LOGGER.error(f"Gagal menulis metadata untuk {audio_path}: {e}")
        import traceback
        traceback.print_exc()


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
    
    if data.get('mqa_details'):
        mqa_file = data['mqa_details']
        encoder_time = datetime.now().strftime("%b %d %Y %H:%M:%S")
        mqa_encoder_str = f'MQAEncode v1.1, 2.4.0+0 (278f5dd), E24F1DE5-32F1-4930-8197-24954EB9D6F4, {encoder_time}'
        handle.tags['ENCODER'] = mqa_encoder_str
        handle.tags['MQAENCODER'] = mqa_encoder_str
        handle.tags['ORIGINALSAMPLERATE'] = str(mqa_file.original_sample_rate)
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_mp3(data, handle, dur_ms=0):
    if handle.tags is None:
            handle.add_tags()
    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    if track_total and track_total != '0':
        track_pos = f"{track_num}/{track_total}"
    else:
        track_pos = track_num
        
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    
    if disc_total and disc_total != '0':
        disc_pos = f"{disc_num}/{disc_total}"
    else:
        disc_pos = disc_num
        
    genre_text = data.get('genre') or ''
    composer_text = data.get('composer') or ''

    handle.tags.add(TIT2(encoding=3, text=data['title']))
    handle.tags.add(TALB(encoding=3, text=data['album']))
    
    handle.tags.add(TPE2(encoding=3, text=data['albumartist']))
    handle.tags.add(TOPE(encoding=3, text=data['albumartist'])) 

    handle.tags.add(TPE1(encoding=3, text=data['artist']))
    handle.tags.add(TCOP(encoding=3, text=data['copyright']))
    handle.tags.add(TRCK(encoding=3, text=track_pos)) 
    if disc_pos: 
        handle.tags.add(TPOS(encoding=3, text=disc_pos)) 
    if genre_text: 
        handle.tags.add(TCON(encoding=3, text=genre_text)) 
    
    if data.get('date'): 
        handle.tags.add(TDRC(encoding=3, text=data['date']))
        
    if data.get('release_date'): 
        handle.tags.add(TDRL(encoding=3, text=data['release_date']))

    if data.get('subgenre'): 
        handle.tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data.get('subgenre')))
    
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'):
        handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if composer_text: 
        handle.tags.add(TCOM(encoding=3, text=composer_text)) 
    
    if dur_ms > 0:
         handle.tags.add(TLEN(encoding=3, text=str(dur_ms)))

    if data.get('bit_depth'):
        handle.tags.add(TXXX(encoding=3, desc='BPS', text=str(data['bit_depth'])))
    if data.get('sample_rate'):
        handle.tags.add(TXXX(encoding=3, desc='SAMPLERATE', text=str(int(data['sample_rate'] * 1000))))
    
    await savePic(handle, data)
    handle.save()
    return True

async def set_wav(data, handle, dur_ms=0):
    # Re-cast aman untuk memastikan objek WAVE
    if not isinstance(handle, WAVE):
        try:
            handle = WAVE(data['filepath'])
        except Exception:
            pass # Jika gagal, gunakan handle yang ada (best effort)

    if handle.tags is None:
        try:
            handle.add_tags()
        except Exception as e:
            LOGGER.error(f"Gagal add_tags WAVE: {e}")
            return
    
    tags = handle.tags

    track_num = str(data.get('tracknumber', ''))
    track_total = str(data.get('totaltracks', ''))
    if track_total and track_total != '0':
        track_pos = f"{track_num}/{track_total}"
    else:
        track_pos = track_num
        
    disc_num = str(data.get('volume') or '')
    disc_total = str(data.get('totalvolume') or '')
    if disc_total and disc_total != '0':
        disc_pos = f"{disc_num}/{disc_total}"
    else:
        disc_pos = disc_num
        
    genre_text = data.get('genre') or ''
    composer_text = data.get('composer') or ''

    tags.add(TIT2(encoding=3, text=data['title']))
    tags.add(TALB(encoding=3, text=data['album']))
    
    tags.add(TPE2(encoding=3, text=data['albumartist']))
    tags.add(TOPE(encoding=3, text=data['albumartist']))

    tags.add(TPE1(encoding=3, text=data['artist']))
    tags.add(TCOP(encoding=3, text=data['copyright']))
    tags.add(TRCK(encoding=3, text=track_pos)) 
    
    if disc_pos: 
        tags.add(TPOS(encoding=3, text=disc_pos)) 
    if genre_text: 
        tags.add(TCON(encoding=3, text=genre_text)) 
    
    if data.get('date'): 
        tags.add(TDRC(encoding=3, text=data['date']))
        
    if data.get('release_date'): 
        tags.add(TDRL(encoding=3, text=data['release_date']))

    if data.get('subgenre'): 
        tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data.get('subgenre')))
    
    tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'):
        tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if composer_text: 
        tags.add(TCOM(encoding=3, text=composer_text)) 

    if dur_ms > 0:
         tags.add(TLEN(encoding=3, text=str(dur_ms)))

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
    
    if data.get('genre'):
        handle.tags['\u00a9gen'] = data['genre']
    if data.get('composer'):
        handle.tags['\u00a9wrt'] = data['composer']
    
    track_number_str = str(data.get('tracknumber') or '')
    totaltracks_str = str(data.get('totaltracks') or '')
    volume_str = str(data.get('volume') or '') 
    totalvolume_str = str(data.get('totalvolume') or '') 
    
    if data.get('date'): 
        handle.tags['\u00a9day'] = data['date']
    
    handle.tags['\u00a9cpr'] = data['copyright']

    if data.get('subgenre'): 
        handle.tags['----:com.apple.iTunes:SUBGENRE'] = data.get('subgenre').encode('utf-8')
        
    if data.get('release_date'): 
        handle.tags['----:com.apple.iTunes:RELEASETIME'] = data.get('release_date').encode('utf-8')

    def safe_int(x):
        try: return int(x)
        except: return 0

    track_number = safe_int(track_number_str)
    totaltracks = safe_int(totaltracks_str)
    volume = safe_int(volume_str)
    totalvolume = safe_int(totalvolume_str)

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
    except Exception as e:
        LOGGER.error(e)
        return
    
    if isinstance(handle, FLAC):
        pic = Picture()
        pic.data = data
        pic.mime = u"image/jpeg"
        handle.clear_pictures()
        handle.add_picture(pic)
    
    elif isinstance(handle, MP4):
        pic = MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)
        handle.tags['covr'] = [pic]

    elif isinstance(handle, (MP3, EasyMP3, WAVE)) or hasattr(handle, 'tags'):
        try:
            handle.tags.delall("APIC")
            handle.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=data))
        except Exception:
            pass


async def get_audio_extension(path):
    try:
        handle = File(path)
        # Handle if None (serupa logic di atas)
        if handle is None:
             ext = os.path.splitext(path)[1].lower()
             return ext.replace('.', '')
             
        if isinstance(handle, MP4): return 'm4a'
        if isinstance(handle, FLAC): return 'flac'
        if isinstance(handle, WAVE): return 'wav'
        return 'mp3'
    except:
        return 'mp3'

async def _download_cover_with_headers(url: str, destination: str):
    if not url:
        return "No URL provided"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/5.37.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/5.37.36'
    }
    
    try:
        dir_path = os.path.dirname(destination)
        os.makedirs(dir_path, exist_ok=True)
    except Exception as e:
        return f"Gagal membuat direktori {dir_path}: {e}"

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=60) as response:
                if response.status == 200:
                    async with aiofiles.open(destination, 'wb') as f:
                        await f.write(await response.read())
                    return None 
                else:
                    return f"HTTP Status: {response.status} (URL: {url})"
    except Exception as e:
        return f"Exception: {e} (URL: {url})"


async def create_cover_file(url:str, meta:dict, thumbnail=False): 
    filename = f"{meta['itemid']}-thumb.jpg" if thumbnail else f"{meta['itemid']}.jpg"
    cover = meta['tempfolder'] + filename
    if not os.path.exists(cover):
        err = await _download_cover_with_headers(url, cover) 
        if err:
            LOGGER.error(f"Gagal mengunduh cover art: {err}")
            return './project-siesta.png'
    if os.path.exists(cover) and os.path.getsize(cover) > 0:
        return cover
    else:
        return './project-siesta.png'
