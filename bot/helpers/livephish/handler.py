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

# Tag Branding
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
    """Mengubah format tanggal LivePhish menjadi standar ISO (YYYY-MM-DD)."""
    if not date_str: return ""
    date_str = str(date_str).strip()
    formats = ["%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d", "%b %d, %Y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError: continue
    return date_str.replace("/", "-")

async def clean_audio_metadata(input_path):
    """
    OPSI NUKLIR: Menggunakan FFmpeg untuk membuang SEMUA metadata bawaan file.
    Ini satu-satunya cara ampuh menghapus 'powered by nugs.net'.
    """
    temp_output = input_path + ".clean.m4a"
    if input_path.endswith(".flac"):
        temp_output = input_path + ".clean.flac"
        
    try:
        # -map_metadata -1 artinya: JANGAN COPY metadata apapun dari input
        # -c copy artinya: Copy stream audio tanpa encode ulang (cepat & tanpa penurunan kualitas)
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-map_metadata", "-1", 
            "-c", "copy",
            temp_output
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        # Jika sukses, timpa file asli dengan file bersih
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, input_path)
            return True
    except Exception as e:
        LOGGER.error(f"Gagal membersihkan metadata: {e}")
        if os.path.exists(temp_output):
            os.remove(temp_output)
    return False

async def extract_cover_from_audio(audio_path, output_path):
    """Ekstrak cover embedded."""
    try:
        cmd = ["ffmpeg", "-y", "-i", audio_path, "-an", "-vcodec", "copy", output_path]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
    except: pass
    return False

async def start_livephish(link: str, user: dict):
    client = user.get('livephish_api')
    if not client: raise Exception("Internal Error: LivePhish Client not passed.")

    match = ID_REGEX.search(link)
    if not match: raise Exception(f"Gagal mengekstrak Album ID dari link: {link}")
    album_id = match.group(1)

    await edit_message(user['bot_msg'], f"Mengambil metadata ID: {album_id}...")
    
    meta_json = await client.get_album_meta(album_id)
    resp = meta_json.get("Response", {})
    if not resp: raise Exception(f"Gagal metadata ID {album_id}: Response kosong.")

    # --- METADATA ALBUM ---
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

    # --- FIX 3: GENRE LOGIC (Looping semua kemungkinan) ---
    genre = "Phish" # Fallback awal
    
    # Cek 'genres' (bisa list of strings atau list of dicts)
    if resp.get("genres"):
        g_list = resp["genres"]
        if isinstance(g_list, list) and len(g_list) > 0:
            first_g = g_list[0]
            if isinstance(first_g, dict):
                genre = first_g.get("name", "Rock")
            else:
                genre = str(first_g)
    
    # Cek 'styles' (biasanya lebih spesifik)
    elif resp.get("styles"):
        s_list = resp["styles"]
        if isinstance(s_list, list) and len(s_list) > 0:
            genre = str(s_list[0])
            
    # Cek field 'genre' langsung
    elif resp.get("genre"):
        genre = str(resp.get("genre"))
        
    # Jika masih default/kosong, set ke Rock
    if not genre or genre == "Phish":
        genre = "Rock"

    # --- FIX 2: LABEL & COPYRIGHT ---
    label = resp.get("recordLabel") or resp.get("label") or resp.get("copyright") or "LivePhish"
    copyright_txt = resp.get("copyright") or f"© {year} {label}"

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    max_disc = 1
    for t in tracks:
        d = t.get("discNum", 1)
        if d > max_disc: max_disc = d

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
        'genre': genre, # Genre sudah diperbaiki
        'copyright': copyright_txt,
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
        
        try: duration = int(float(t.get("length", 0)))
        except: duration = 0
            
        # --- FIX 2: COMPOSER & ISRC ---
        composer = t.get("author") or t.get("composer") or t.get("writer") or ""
        isrc_val = t.get("isrc") or t.get("ISRC") or ""

        prog_txt = get_progress_bar_text(i+1, total_tracks, title, "Album")
        try: await edit_message(user['bot_msg'], prog_txt)
        except: pass

        try: stream_url = await client.get_stream_url(track_id, livephish_manager.quality)
        except: stream_url = None

        if not stream_url:
            LOGGER.error(f"Stream URL kosong: {title}")
            continue

        ext = ".m4a"
        if livephish_manager.quality == "FLAC": ext = ".flac"

        clean_title = sanitize_name(title)
        fname = f"{track_num_padded} - {clean_title}{ext}"
        full_file_path = os.path.join(base_meta['tempfolder'], fname)
        base_meta['folderpath'] = base_meta['tempfolder']

        # 1. DOWNLOAD
        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # 2. EKSTRAK COVER (Sebelum dibersihkan)
        if not cover_found and os.path.exists(full_file_path):
            if await extract_cover_from_audio(full_file_path, extracted_cover_path):
                base_meta['cover'] = extracted_cover_path
                cover_found = True
                LOGGER.info(f"LivePhish: Cover extracted.")

        # --- FIX 1: BERSIHKAN METADATA 'NUGS.NET' (OPSI NUKLIR) ---
        # Kita hapus semua tag dari file menggunakan FFmpeg sebelum menulis tag kita sendiri
        await clean_audio_metadata(full_file_path)

        # 3. SET METADATA BARU
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
            'genre': genre
        })

        # Masukkan Tag Branding
        branding_dict = {
            'comment': BRANDING_TAG, 'COMMENT': BRANDING_TAG,
            'description': BRANDING_TAG, 'DESCRIPTION': BRANDING_TAG,
            'encoded_by': BRANDING_TAG, 'ENCODED_BY': BRANDING_TAG
        }
        track_meta.update(branding_dict)

        if ext == ".flac":
            track_meta['discnumber'] = f"{disc_num}/{max_disc}"
            track_meta['DISCNUMBER'] = f"{disc_num}/{max_disc}"
            track_meta['tracknumber'] = f"{raw_track_num}/{total_tracks}"
            track_meta['TRACKNUMBER'] = f"{raw_track_num}/{total_tracks}"
            
            # Mapping Lengkap untuk FLAC
            track_meta['ORGANIZATION'] = label
            track_meta['LABEL'] = label
            track_meta['COMPOSER'] = composer
            track_meta['ISRC'] = isrc_val
            track_meta['GENRE'] = genre
            track_meta['COPYRIGHT'] = copyright_txt
            track_meta['DATE'] = release_date
            
            # Fallback
            track_meta['totaldiscs'] = str(max_disc)
            track_meta['totaltracks'] = str(total_tracks)
            
        elif ext == ".m4a":
            track_meta['discnumber'] = str(disc_num)
            track_meta['totaldiscs'] = str(max_disc)
            track_meta['tracknumber'] = str(raw_track_num)
            track_meta['totaltracks'] = str(total_tracks)
            
            track_meta['copyright'] = copyright_txt
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
