import re
import os
import aiohttp
import asyncio
from datetime import datetime
from config import Config
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

# Import Helper standar
from bot.helpers.utils import download_file, zip_handler, fetch_zip_settings
from bot.helpers.uploder import track_upload, album_upload, post_art_poster
from bot.helpers.message import edit_message
from bot.logger import LOGGER

# Regex ID LivePhish
ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

def sanitize_name(name):
    """Membersihkan nama file/folder."""
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def get_progress_bar_text(current, total, title, type_str):
    """Visual Progress Bar."""
    percentage = current / total
    filled_length = int(10 * percentage)
    bar = '▰' * filled_length + '▱' * (10 - filled_length)
    
    text = (
        f"╭─ ᴘʀᴏɢʀᴇss\n"
        f"│\n"
        f"├ {bar}\n"
        f"│\n"
        f"├ ᴅᴏɴᴇ : {current} / {total}\n"
        f"│\n"
        f"├ ᴛɪᴛʟᴇ : {title}\n"
        f"│\n"
        f"╰─ ᴛʏᴘᴇ : {type_str}"
    )
    return text

def format_date_standard(date_str):
    """
    Mengubah format tanggal LivePhish menjadi standar ISO (YYYY-MM-DD).
    Menangani: MM/DD/YYYY, YYYY/MM/DD, dll.
    """
    if not date_str:
        return ""
    
    date_str = date_str.strip()
    
    # Daftar format yang mungkin masuk
    formats = [
        "%m/%d/%Y", # 12/30/2025 (Format US Umum)
        "%Y/%m/%d", # 2025/12/30 (Format yang Anda hindari)
        "%Y-%m-%d", # 2025-12-30 (Sudah benar)
        "%b %d, %Y", # Dec 30, 2025
        "%d/%m/%Y", # 30/12/2025
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d") # Output wajib YYYY-MM-DD
        except ValueError:
            continue
            
    # Jika gagal parsing, kembalikan string asli tapi ganti slash jadi dash sebagai fallback
    return date_str.replace("/", "-")

async def extract_cover_from_audio(audio_path, output_path):
    """
    Mengekstrak cover art (embedded) dari file audio menggunakan FFmpeg.
    """
    try:
        cmd = [
            "ffmpeg", "-y", "-i", audio_path, 
            "-an", "-vcodec", "copy", output_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
    except Exception as e:
        LOGGER.error(f"Gagal ekstrak cover dari file audio: {e}")
    return False

async def start_livephish(link: str, user: dict):
    client = user.get('livephish_api')
    if not client:
        raise Exception("Internal Error: LivePhish Client not passed.")

    match = ID_REGEX.search(link)
    if not match:
        raise Exception(f"Gagal mengekstrak Album ID dari link: {link}")
    album_id = match.group(1)

    await edit_message(user['bot_msg'], f"Mengambil metadata ID: {album_id}...")
    
    meta_json = await client.get_album_meta(album_id)
    resp = meta_json.get("Response", {})
    if not resp:
        raise Exception(f"Gagal metadata ID {album_id}: Response kosong.")

    # Metadata Album
    raw_album = resp.get("containerInfo", "Unknown Album")
    raw_artist = resp.get("artistName", "Phish")
    album_name = sanitize_name(raw_album)
    artist_name = sanitize_name(raw_artist)
    
    # --- LOGIKA TANGGAL (FIX: YYYY-MM-DD) ---
    raw_date = ""
    # Cek berbagai field tanggal
    possible_keys = ["performanceDate", "releaseDateFormatted", "performanceDateFormatted", "performanceDateYear"]
    for k in possible_keys:
        val = str(resp.get(k) or "")
        if val:
            raw_date = val
            break

    # Format menjadi YYYY-MM-DD
    release_date = format_date_standard(raw_date)
    
    # Ambil Tahun (4 digit pertama)
    year = release_date[:4] if len(release_date) >= 4 else ""

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    # Hitung Total Volume
    max_disc = 1
    for t in tracks:
        d = t.get("discNum", 1)
        if d > max_disc:
            max_disc = d

    # --- SETUP FOLDER ---
    folder_name = f"{artist_name} - {album_name}"
    if len(folder_name) > 150: folder_name = folder_name[:150]
    
    base_folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), folder_name)

    base_meta = {
        'title': album_name,
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': release_date, # Format: YYYY-MM-DD
        'cover': "", 
        'totaltracks': str(total_tracks),
        'totalvolume': str(max_disc),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, 
        'type': 'album', 
        'genre': 'Rock',
        'copyright': 'LivePhish',
        'explicit': False
    }
    
    completed_tracks = []
    
    init_txt = get_progress_bar_text(0, total_tracks, album_name, "Album")
    await edit_message(user['bot_msg'], init_txt)

    extracted_cover_path = os.path.join(base_folder_path, "cover.jpg")
    cover_found = False

    for i, t in enumerate(tracks):
        track_id = t.get("trackID") or t.get("songID")
        title = t.get("songTitle", f"Track {i+1}")
        
        raw_track_num = t.get("trackNum", i+1)
        track_num_padded = f"{int(raw_track_num):02d}"
        
        disc_num = t.get("discNum", 1)
        
        try:
            duration = int(float(t.get("length", 0)))
        except:
            duration = 0
        
        # Update Progress Bar
        prog_txt = get_progress_bar_text(i+1, total_tracks, title, "Album")
        try: await edit_message(user['bot_msg'], prog_txt)
        except: pass

        try:
            stream_url = await client.get_stream_url(track_id, livephish_manager.quality)
        except:
            stream_url = None

        if not stream_url:
            LOGGER.error(f"Stream URL kosong: {title}")
            continue

        ext = ".m4a"
        if livephish_manager.quality == "FLAC":
            ext = ".flac"

        clean_title = sanitize_name(title)
        fname = f"{track_num_padded} - {clean_title}{ext}"
        
        full_file_path = os.path.join(base_meta['tempfolder'], fname)
        base_meta['folderpath'] = base_meta['tempfolder']

        # 1. DOWNLOAD TRACK
        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # 2. EKSTRAK COVER
        if not cover_found and os.path.exists(full_file_path):
            if await extract_cover_from_audio(full_file_path, extracted_cover_path):
                base_meta['cover'] = extracted_cover_path
                cover_found = True
                LOGGER.info(f"LivePhish: Berhasil ekstrak cover dari file {fname}")

        # 3. SET METADATA
        track_meta = base_meta.copy()
        track_meta.update({
            'title': title,
            'tracknumber': str(raw_track_num),
            'volume': str(disc_num),
            'filepath': full_file_path,
            'itemid': str(track_id),
            'duration': duration,
            'extension': ext.replace(".", "")
        })

        # --- FIX 1: METADATA KHUSUS FLAC ---
        # Memastikan field Part/Total dkk terbaca oleh tagger FLAC
        if ext == ".flac":
            track_meta['discnumber'] = str(disc_num)       # Part/Position
            track_meta['totaldiscs'] = str(max_disc)       # Part/Total (Discs)
            track_meta['tracktotal'] = str(total_tracks)   # Track Total
            # Pastikan copyright masuk
            track_meta['copyright'] = base_meta['copyright']
            
        # --- FIX 2: HAPUS COMMENT DI ALAC ---
        # ALAC biasanya menggunakan ekstensi .m4a
        if ext == ".m4a" or livephish_manager.quality != "FLAC":
            track_meta['comment'] = "" # Kosongkan tag Comment

        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    # --- UPLOAD ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

        # ZIP
        if album_zip:
            await edit_message(user['bot_msg'], f"Membuat file ZIP...\n{album_name}")
            base_meta['zip_path'] = await zip_handler(base_meta['folderpath'])

        # ART POSTER
        if art_poster:
            if cover_found and os.path.exists(base_meta['cover']):
                try:
                    base_meta['poster_msg'] = await post_art_poster(user, base_meta)
                except Exception as e:
                    LOGGER.error(f"Gagal poster: {e}")

        await edit_message(user['bot_msg'], f"Mengunggah...\n{album_name}")
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
