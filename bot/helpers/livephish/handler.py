# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import os
import aiohttp
import asyncio
import urllib.parse
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

# --- TEKNIK BRUTE FORCE COVER HD ---
async def fetch_website_cover_hd(url):
    """
    Mencari cover art resolusi MAKSIMAL dengan mencoba variasi URL.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    # 1. Kumpulkan kandidat gambar
                    # Kita cari yang mengandung 'shows', 'release', atau 'static.livephish'
                    matches = re.findall(r'(https?://static\.livephish\.com/images/[^"\']+\.jpg)', html)
                    
                    candidate = None
                    # Prioritaskan gambar yang namanya terlihat seperti cover album utama
                    for m in matches:
                        if "_200" in m or "_400" in m or "shows" in m:
                            candidate = m
                            break # Ambil satu sampel untuk di-upscale
                    
                    # Fallback ke OG Image jika tidak ada match
                    if not candidate:
                        match_og = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
                        if match_og: candidate = match_og.group(1)

                    if candidate:
                        # Normalize URL
                        if candidate.startswith("//"): candidate = "https:" + candidate
                        
                        # --- ALGORITMA BRUTE FORCE RESOLUSI ---
                        
                        # 1. Buat versi "Clean" (Master File)
                        # Hapus _200, _400, _v1, _mini, dll sebelum .jpg
                        # Contoh: ph160102_200.jpg -> ph160102.jpg
                        clean_url = re.sub(r'(_\d+|_v\d+|_mini|_med|_small|_large)(\.jpg)$', r'\2', candidate)
                        
                        LOGGER.info(f"Mencoba URL Master: {clean_url}")
                        try:
                            async with session.head(clean_url) as hd_resp:
                                if hd_resp.status == 200:
                                    # Jika master file ada, ini pasti resolusi tertinggi
                                    return clean_url
                        except: pass
                        
                        # 2. Jika Master gagal, coba suffix '_large' atau '_high' (kadang dipakai)
                        suffixes = ["_large", "_high"]
                        base_clean = clean_url.replace(".jpg", "")
                        for s in suffixes:
                            try_url = f"{base_clean}{s}.jpg"
                            try:
                                async with session.head(try_url) as s_resp:
                                    if s_resp.status == 200:
                                        return try_url
                            except: pass

                        # 3. Jika semua gagal, kembalikan kandidat awal (minimal ada gambar)
                        LOGGER.warning("Gagal mendapatkan Master URL, menggunakan fallback.")
                        return candidate

    except Exception as e:
        LOGGER.warning(f"Gagal scrape Cover Website: {e}")
    return None

async def clean_audio_metadata(input_path):
    """OPSI NUKLIR: Menghapus total metadata bawaan."""
    temp_output = input_path + ".clean.m4a"
    if input_path.endswith(".flac"):
        temp_output = input_path + ".clean.flac"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-map_metadata", "-1", "-map_metadata:g", "-1",
            "-c", "copy", temp_output
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, input_path)
            return True
    except:
        if os.path.exists(temp_output): os.remove(temp_output)
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
    
    raw_date = ""
    for k in ["performanceDate", "releaseDateFormatted", "performanceDateFormatted", "performanceDateYear"]:
        if resp.get(k):
            raw_date = str(resp.get(k))
            break
    release_date = format_date_standard(raw_date)
    year = release_date[:4] if len(release_date) >= 4 else ""

    genre = "Rock"
    if resp.get("styles") and isinstance(resp["styles"], list) and len(resp["styles"]) > 0:
        genre = str(resp["styles"][0])
    elif resp.get("genres") and isinstance(resp["genres"], list) and len(resp["genres"]) > 0:
        g = resp["genres"][0]
        genre = g.get("name", "Rock") if isinstance(g, dict) else str(g)
    elif resp.get("genre"):
        genre = str(resp.get("genre"))

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

    # --- DOWNLOAD COVER (DENGAN BRUTE FORCE HD) ---
    cover_url = None
    LOGGER.info("Mencari cover art HD via Web Scraper...")
    
    # 1. Coba Scraper Website (Prioritas Resolusi Tinggi)
    cover_url = await fetch_website_cover_hd(link)
        
    if not cover_url:
        # 2. Fallback ke API Pics (biasanya kualitas medium/low)
        pics = resp.get("pics", [])
        if pics:
            pics.sort(key=lambda x: x.get("width", 0), reverse=True)
            for p in pics:
                if p.get("url"): 
                    raw_url = p.get("url")
                    if raw_url.startswith("/"): cover_url = "https://static.livephish.com" + raw_url
                    else: cover_url = raw_url
                    break

    final_cover_path = ""
    if cover_url:
        try:
            temp_path = await create_cover_file(
                cover_url, {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
            )
            if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                 if "project-siesta" not in temp_path:
                    final_cover_path = temp_path
        except Exception as e:
            LOGGER.error(f"Gagal download cover: {e}")

    base_meta = {
        'title': album_name,
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': release_date,
        'cover': final_cover_path,
        'totaltracks': str(total_tracks),
        'totalvolume': str(max_disc),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, 
        'type': 'album', 
        'genre': genre,
        'copyright': copyright_txt,
        'label': label,
        'explicit': False
    }
    
    completed_tracks = []
    
    init_txt = get_progress_bar_text(0, total_tracks, album_name, "Album")
    await edit_message(user['bot_msg'], init_txt)

    for i, t in enumerate(tracks):
        track_id = t.get("trackID") or t.get("songID")
        title = t.get("songTitle", f"Track {i+1}")
        
        raw_track_num = t.get("trackNum", i+1)
        track_num_padded = f"{int(raw_track_num):02d}"
        disc_num = t.get("discNum", 1)
        
        try: duration = int(float(t.get("length", 0)))
        except: duration = 0
            
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
        
        # --- LOGIKA FOLDER DISC (Agar ZIP tidak rusak) ---
        if int(base_meta['totalvolume']) > 1:
            disc_folder = os.path.join(base_meta['tempfolder'], f"Disc {disc_num}")
            if not os.path.exists(disc_folder):
                os.makedirs(disc_folder, exist_ok=True)
            current_save_path = disc_folder
        else:
            current_save_path = base_meta['tempfolder']

        # Nama File Murni
        fname = f"{track_num_padded} - {clean_title}{ext}"
        
        full_file_path = os.path.join(current_save_path, fname)
        
        # Download
        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # Nuklir Metadata
        await clean_audio_metadata(full_file_path)

        # Set Metadata
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
            track_meta['ORGANIZATION'] = label
            track_meta['LABEL'] = label
            track_meta['COMPOSER'] = composer
            track_meta['ISRC'] = isrc_val
            track_meta['GENRE'] = genre
            track_meta['COPYRIGHT'] = copyright_txt
            track_meta['DATE'] = release_date
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
            if base_meta.get('cover') and os.path.exists(base_meta['cover']):
                try:
                    base_meta['poster_msg'] = await post_art_poster(user, base_meta)
                except Exception as e:
                    LOGGER.error(f"Gagal poster: {e}")

        await edit_message(user['bot_msg'], f"Mengunggah...\n{album_name}")
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
