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

# Branding Tag (Untuk menimpa nugs.net)
BRANDING_TAG = "powered by livephish.com"

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
    """
    if not date_str:
        return ""
    date_str = str(date_str).strip()
    
    formats = [
        "%m/%d/%Y", # 12/30/2025
        "%Y/%m/%d", # 2025/12/30
        "%Y-%m-%d", # 2025-12-30
        "%b %d, %Y", # Dec 30, 2025
        "%d/%m/%Y", # 30/12/2025
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.replace("/", "-")

async def extract_cover_from_audio(audio_path, output_path):
    """Ekstrak cover embedded dari file audio."""
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
    except:
        pass
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

    # --- 1. METADATA ALBUM ---
    raw_album = resp.get("containerInfo", "Unknown Album")
    raw_artist = resp.get("artistName", "Phish")
    album_name = sanitize_name(raw_album)
    artist_name = sanitize_name(raw_artist)
    
    # Tanggal
    raw_date = ""
    for k in ["performanceDate", "releaseDateFormatted", "performanceDateFormatted", "performanceDateYear"]:
        if resp.get(k):
            raw_date = str(resp.get(k))
            break
    release_date = format_date_standard(raw_date)
    year = release_date[:4] if len(release_date) >= 4 else ""

    # Genre (Dinamis, prioritas: styles -> genres -> containerInfo -> Rock)
    genre = "Rock"
    if resp.get("styles") and isinstance(resp["styles"], list) and len(resp["styles"]) > 0:
        genre = resp["styles"][0]
    elif resp.get("genres") and isinstance(resp["genres"], list) and len(resp["genres"]) > 0:
        # Kadang genres adalah list of dict
        g = resp["genres"][0]
        genre = g.get("name", "Rock") if isinstance(g, dict) else str(g)
    elif resp.get("genre"):
        genre = resp.get("genre")

    # Label / Copyright
    # LivePhish API: recordLabel, copyright, atau gunakan Artist sebagai fallback label
    label = resp.get("recordLabel") or resp.get("copyright") or resp.get("label") or "LivePhish"

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    # Hitung Total Volume
    max_disc = 1
    for t in tracks:
        d = t.get("discNum", 1)
        if d > max_disc: max_disc = d

    # Folder Setup
    folder_name = f"{artist_name} - {album_name}"
    if len(folder_name) > 150: folder_name = folder_name[:150]
    base_folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), folder_name)

    base_meta = {
        'title': album_name,
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': release_date,
        'cover': "", 
        'totaltracks': str(total_tracks),
        'totalvolume': str(max_disc),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, 
        'type': 'album', 
        'genre': genre,
        'copyright': label,
        'label': label,
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
            
        # --- 2. METADATA TRACK ---
        composer = t.get("author") or t.get("composer") or ""
        isrc_val = t.get("isrc") or t.get("ISRC") or ""

        # Update Progress
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

        # Download
        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # Ekstrak Cover
        if not cover_found and os.path.exists(full_file_path):
            if await extract_cover_from_audio(full_file_path, extracted_cover_path):
                base_meta['cover'] = extracted_cover_path
                cover_found = True
                LOGGER.info(f"LivePhish: Cover extracted.")

        # Construct Metadata
        track_meta = base_meta.copy()
        track_meta.update({
            'title': title,
            'tracknumber': str(raw_track_num),
            'volume': str(disc_num),
            'filepath': full_file_path,
            'itemid': str(track_id),
            'duration': duration,
            'extension': ext.replace(".", ""),
            'isrc': isrc_val,
            'composer': composer,
            'label': label,
            'genre': genre,
        })

        # --- 3. FORCE OVERWRITE NUGS.NET (SEMUA FORMAT) ---
        # Kita set semua kemungkinan key komentar/deskripsi dengan branding kita
        # Ini penting karena tagger yang berbeda menggunakan key yang berbeda
        branding_dict = {
            'comment': BRANDING_TAG,
            'COMMENT': BRANDING_TAG,
            'description': BRANDING_TAG,
            'DESCRIPTION': BRANDING_TAG,
            'long_description': BRANDING_TAG,
            'LONG_DESCRIPTION': BRANDING_TAG,
            'encoded_by': BRANDING_TAG,
            'ENCODED_BY': BRANDING_TAG
        }
        track_meta.update(branding_dict)

        # --- 4. FORMAT-SPECIFIC MAPPING ---
        if ext == ".flac":
            # Agar terbaca sebagai Part/Position (Current/Total) di MediaInfo
            # formatnya harus "X/Y"
            track_meta['discnumber'] = f"{disc_num}/{max_disc}"
            track_meta['DISCNUMBER'] = f"{disc_num}/{max_disc}"
            
            # Agar terbaca sebagai Track/Total
            track_meta['tracknumber'] = f"{raw_track_num}/{total_tracks}"
            track_meta['TRACKNUMBER'] = f"{raw_track_num}/{total_tracks}"
            
            # Standard Keys FLAC
            track_meta['ORGANIZATION'] = label
            track_meta['LABEL'] = label
            track_meta['COMPOSER'] = composer
            track_meta['ISRC'] = isrc_val
            track_meta['GENRE'] = genre
            track_meta['COPYRIGHT'] = label
            track_meta['DATE'] = release_date
            
            # Fallback untuk tagger yang strict
            track_meta['totaldiscs'] = str(max_disc)
            track_meta['totaltracks'] = str(total_tracks)
            track_meta['tracktotal'] = str(total_tracks)
            track_meta['disctotal'] = str(max_disc)
            
        elif ext == ".m4a":
            # ALAC/M4A atoms
            track_meta['discnumber'] = str(disc_num)
            track_meta['totaldiscs'] = str(max_disc)
            track_meta['tracknumber'] = str(raw_track_num)
            track_meta['totaltracks'] = str(total_tracks)
            
            track_meta['copyright'] = label
            track_meta['label'] = label
            track_meta['composer'] = composer
            track_meta['genre'] = genre
            track_meta['date'] = release_date

        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    # --- UPLOAD ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

        if album_zip:
            await edit_message(user['bot_msg'], f"Membuat file ZIP...\n{album_name}")
            base_meta['zip_path'] = await zip_handler(base_meta['folderpath'])

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
