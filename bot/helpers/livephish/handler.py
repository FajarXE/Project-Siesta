# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import os
import aiohttp
import urllib.parse
from config import Config
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

from bot.helpers.utils import download_file, zip_handler, fetch_zip_settings
from bot.helpers.uploder import track_upload, album_upload, post_art_poster
from bot.helpers.message import edit_message
from bot.logger import LOGGER

# Regex ID LivePhish
ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

def sanitize_name(name):
    """Membersihkan nama file/folder."""
    # Hapus karakter ilegal file system
    clean = re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()
    return clean

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

async def get_itunes_cover(artist, album):
    """Mencari cover art di iTunes jika server LivePhish mati."""
    try:
        term = urllib.parse.quote(f"{artist} {album}")
        url = f"https://itunes.apple.com/search?term={term}&entity=album&limit=1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data['resultCount'] > 0:
                        # Ambil resolusi tinggi
                        return data['results'][0]['artworkUrl100'].replace('100x100bb', '1000x1000bb')
    except Exception as e:
        LOGGER.warning(f"iTunes Fallback Error: {e}")
    return None

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
        err_msg = meta_json.get("ResponseStatus", {}).get("message", "Response kosong.")
        raise Exception(f"Gagal metadata ID {album_id}: {err_msg}")

    # Metadata Album
    raw_album = resp.get("containerInfo", "Unknown Album")
    raw_artist = resp.get("artistName", "Phish")
    album_name = sanitize_name(raw_album)
    artist_name = sanitize_name(raw_artist)
    
    year = str(resp.get("performanceDateYear", ""))
    if not year:
        p_date = resp.get("performanceDate") 
        if p_date:
            year = p_date.split("/")[-1]

    # --- LOGIKA COVER ART (LivePhish -> iTunes Fallback) ---
    cover_path = ""
    pics = resp.get("pics", [])
    
    candidates = []
    # 1. Kumpulkan URL dari LivePhish
    if pics:
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        for p in pics:
            raw_url = p.get("url", "")
            if not raw_url: continue
            if raw_url.startswith("/"):
                candidates.append("https://www.livephish.com" + raw_url)
                candidates.append("https://static.livephish.com" + raw_url)
            else:
                candidates.append(raw_url)

    # 2. Coba Download dari LivePhish
    success_cover = False
    for url in candidates:
        try:
            temp_path = await create_cover_file(
                url, 
                {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
            )
            # Cek jika file valid dan BUKAN fallback default (project-siesta)
            if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                if "project-siesta" not in temp_path:
                    cover_path = temp_path
                    success_cover = True
                    break
        except:
            pass

    # 3. JIKA GAGAL: Coba Fallback ke iTunes (Solusi Cover Asli)
    if not success_cover:
        LOGGER.info("Cover LivePhish mati, mencoba mencari di iTunes...")
        itunes_url = await get_itunes_cover(raw_artist, raw_album)
        if itunes_url:
            try:
                temp_path = await create_cover_file(
                    itunes_url, 
                    {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
                )
                if temp_path and os.path.exists(temp_path):
                    cover_path = temp_path
                    LOGGER.info(f"Berhasil mendapatkan cover dari iTunes: {itunes_url}")
            except Exception as e:
                LOGGER.warning(f"Gagal download cover iTunes: {e}")

    # 4. Jika masih gagal, hapus path agar tidak pakai gambar 'Project Siesta'
    if cover_path and "project-siesta" in cover_path:
        cover_path = "" # Lebih baik kosong daripada salah gambar

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    # --- PERBAIKAN NAMA ZIP & FOLDER ---
    folder_name = f"{artist_name} - {album_name}"
    if len(folder_name) > 150: 
        folder_name = folder_name[:150]
    
    # Path folder bersih tanpa trailing slash
    base_folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), folder_name)

    base_meta = {
        'title': album_name, # FIX NAME: N/A
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': year,
        'cover': cover_path,
        'totaltracks': str(total_tracks),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, 
        'type': 'Album', 
        'genre': 'Rock',
        'copyright': 'LivePhish',
        'explicit': False
    }
    
    completed_tracks = []

    # Init Progress
    init_progress = get_progress_bar_text(0, total_tracks, album_name, base_meta['type'])
    await edit_message(user['bot_msg'], init_progress)

    for i, t in enumerate(tracks):
        track_id = t.get("trackID") or t.get("songID")
        title = t.get("songTitle", f"Track {i+1}")
        track_num = t.get("trackNum", str(i+1))
        disc_num = t.get("discNum", 1)
        
        try:
            duration = int(float(t.get("length", 0)))
        except:
            duration = 0
        
        # Update Progress Bar
        progress_text = get_progress_bar_text(i+1, total_tracks, title, base_meta['type'])
        try:
            await edit_message(user['bot_msg'], progress_text)
        except:
            pass

        try:
            stream_url = await client.get_stream_url(track_id, livephish_manager.quality)
        except Exception as e:
            LOGGER.error(f"LivePhish API Error: {e}")
            stream_url = None

        if not stream_url:
            LOGGER.error(f"Stream URL kosong untuk: {title}")
            continue

        ext = ".m4a"
        if livephish_manager.quality == "FLAC":
            ext = ".flac"

        clean_title = sanitize_name(title)
        fname = f"{track_num}. {clean_title}{ext}"
        
        full_file_path = os.path.join(base_meta['tempfolder'], fname)
        base_meta['folderpath'] = base_meta['tempfolder'] # Update path untuk ZIP handler

        err = await download_file(stream_url, full_file_path)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        track_meta = base_meta.copy()
        track_meta.update({
            'title': title,
            'tracknumber': str(track_num),
            'volume': str(disc_num),
            'filepath': full_file_path,
            'itemid': str(track_id),
            'duration': duration,
            'extension': ext.replace(".", "")
        })
        
        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    # --- FINALISASI ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

        # 1. Buat ZIP (Nama ZIP akan mengikuti nama folder yang sudah diperbaiki)
        if album_zip:
            await edit_message(user['bot_msg'], f"Membuat file ZIP...\n{album_name}")
            base_meta['zip_path'] = await zip_handler(base_meta['folderpath'])

        # 2. Kirim Art Poster
        if art_poster:
            # Hanya kirim jika cover valid (bukan kosong/siesta)
            if base_meta.get('cover') and os.path.exists(base_meta['cover']):
                try:
                    base_meta['poster_msg'] = await post_art_poster(user, base_meta)
                except Exception as e:
                    LOGGER.error(f"Gagal mengirim Art Poster: {e}")
            else:
                LOGGER.warning("Melewati Art Poster karena cover asli tidak ditemukan.")

        # 3. Upload
        await edit_message(user['bot_msg'], f"Mengunggah...\n{album_name}")
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
