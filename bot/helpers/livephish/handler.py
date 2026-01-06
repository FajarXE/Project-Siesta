# [GANTI FILE: bot/helpers/livephish/handler.py]

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

# --- FUNGSI PENCARI COVER HD (WEB SCRAPER PINTAR) ---
async def fetch_website_cover_hd(url):
    """
    Scrape gambar dari website LivePhish DAN mencoba mendapatkan resolusi asli.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    
                    # 1. Cari semua link gambar static.livephish.com
                    # Pattern: https://static.livephish.com/... .jpg
                    matches = re.findall(r'(https?://static\.livephish\.com/[^"\']+\.jpg)', html)
                    
                    candidate = None
                    
                    # Prioritaskan gambar yang namanya mirip 'show' atau 'release'
                    for m in matches:
                        if "show" in m or "release" in m or "pix" in m:
                            candidate = m
                            break
                    
                    # Jika tidak ada yang spesifik, ambil yang pertama ditemukan (biasanya OG Image)
                    if not candidate:
                        # Fallback ke OG Image
                        match_og = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
                        if match_og:
                            candidate = match_og.group(1)

                    if candidate:
                        # --- TEKNIK UPSCALING URL ---
                        # URL seringkali berbentuk: .../nama_200.jpg (Kecil/Buram)
                        # Kita coba hapus _200, _400, _v, dll untuk dapat yang asli.
                        
                        # 1. Coba versi bersih (hapus semua antara nama dan .jpg)
                        # Contoh: file_200.jpg -> file.jpg
                        hd_url = re.sub(r'(_\d+|_\w+)(\.jpg)$', r'\2', candidate)
                        
                        # Cek apakah URL HD ini hidup?
                        try:
                            async with session.head(hd_url) as hd_resp:
                                if hd_resp.status == 200:
                                    LOGGER.info(f"Cover HD Ditemukan: {hd_url}")
                                    return hd_url
                        except:
                            pass
                        
                        # Jika versi HD mati, gunakan candidate awal (mungkin sudah HD atau terbaik yg ada)
                        if candidate.startswith("//"): candidate = "https:" + candidate
                        LOGGER.info(f"Cover Website Ditemukan: {candidate}")
                        return candidate

    except Exception as e:
        LOGGER.warning(f"Gagal scrape Cover Website: {e}")
    return None

async def clean_audio_metadata(input_path):
    """
    OPSI NUKLIR: Menghapus total metadata bawaan (powered by nugs.net).
    """
    temp_output = input_path + ".clean.m4a"
    if input_path.endswith(".flac"):
        temp_output = input_path + ".clean.flac"
        
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-map_metadata", "-1", "-map_metadata:g", "-1",
            "-c", "copy",
            temp_output
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, input_path)
            return True
    except Exception as e:
        LOGGER.error(f"Gagal cleaning metadata: {e}")
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
    
    # Tanggal
    raw_date = ""
    for k in ["performanceDate", "releaseDateFormatted", "performanceDateFormatted", "performanceDateYear"]:
        if resp.get(k):
            raw_date = str(resp.get(k))
            break
    release_date = format_date_standard(raw_date)
    year = release_date[:4] if len(release_date) >= 4 else ""

    # Genre Dinamis
    genre = "Rock"
    if resp.get("styles") and isinstance(resp["styles"], list) and len(resp["styles"]) > 0:
        genre = str(resp["styles"][0])
    elif resp.get("genres") and isinstance(resp["genres"], list) and len(resp["genres"]) > 0:
        g = resp["genres"][0]
        genre = g.get("name", "Rock") if isinstance(g, dict) else str(g)
    elif resp.get("genre"):
        genre = str(resp.get("genre"))

    # Label
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

    # --- STRATEGI DOWNLOAD COVER HD ---
    # Scrape Website LivePhish -> Upscale URL -> API -> Kosong
    cover_url = None
    
    LOGGER.info("Mencari cover art HD via Web Scraper...")
    cover_url = await fetch_website_cover_hd(link)
        
    if not cover_url:
        # Fallback API LivePhish
        pics = resp.get("pics", [])
        if pics:
            pics.sort(key=lambda x: x.get("width", 0), reverse=True)
            for p in pics:
                if p.get("url"): 
                    raw_url = p.get("url")
                    if raw_url.startswith("/"):
                        cover_url = "https://static.livephish.com" + raw_url
                    else:
                        cover_url = raw_url
                    break

    # Download Cover
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

    # Metadata Base
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
        fname = f"{track_num_padded} - {clean_title}{ext}"
        full_file_path = os.path.join(base_meta['tempfolder'], fname)
        base_meta['folderpath'] = base_meta['tempfolder']

        # 1. DOWNLOAD
        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # 2. BERSIHKAN METADATA NUGS.NET (Opsi Nuklir)
        await clean_audio_metadata(full_file_path)

        # 3. SET METADATA
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

        # Branding
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
            else:
                 LOGGER.warning("Art Poster dilewati: Cover tidak ditemukan.")

        await edit_message(user['bot_msg'], f"Mengunggah...\n{album_name}")
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
