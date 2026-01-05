# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import os
import aiohttp
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

# Import standar sesuai modul Deezer Anda
from bot.helpers.utils import download_file, zip_handler, fetch_zip_settings
from bot.helpers.uploder import track_upload, album_upload, post_art_poster

from bot.helpers.message import edit_message
from bot.logger import LOGGER
from config import Config

# Regex ID
ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

# URL Fallback (Logo LivePhish) jika API memberikan link mati
FALLBACK_COVER_URL = "https://www.livephish.com/images/logo-livephish-200.png"

def sanitize_name(name):
    """Membersihkan nama file/folder dari karakter ilegal."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

async def check_url_exists(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, timeout=5) as resp:
                return resp.status == 200
    except:
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
        err_msg = meta_json.get("ResponseStatus", {}).get("message", "Response kosong.")
        raise Exception(f"Gagal metadata ID {album_id}: {err_msg}")

    # Metadata Dasar
    raw_album = resp.get("containerInfo", "Unknown Album")
    raw_artist = resp.get("artistName", "Phish")
    
    # Sanitasi untuk nama folder/file
    album_name = sanitize_name(raw_album)
    artist_name = sanitize_name(raw_artist)
    
    # Parsing Tahun
    year = str(resp.get("performanceDateYear", ""))
    if not year:
        p_date = resp.get("performanceDate") 
        if p_date:
            year = p_date.split("/")[-1]

    # --- LOGIKA COVER ART (DENGAN FINAL FALLBACK) ---
    cover_path = ""
    pics = resp.get("pics", [])
    
    # Kumpulkan kandidat URL
    candidates = []
    
    # 1. Dari API (High Res ke Low Res)
    if pics:
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        for p in pics:
            raw_url = p.get("url", "")
            if raw_url:
                if raw_url.startswith("/"):
                    candidates.append("https://www.livephish.com" + raw_url)
                else:
                    candidates.append(raw_url)
                    if "static.livephish.com" in raw_url:
                        candidates.append(raw_url.replace("static.livephish.com", "www.livephish.com"))

    # 2. Tambahkan Fallback Statis (Logo) di urutan terakhir
    candidates.append(FALLBACK_COVER_URL)

    # 3. Coba download satu per satu
    for url in candidates:
        try:
            temp_path = await create_cover_file(
                url, 
                {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
            )
            
            # Cek sukses: File ada, size > 0, dan BUKAN gambar default sistem (project-siesta)
            # Kecuali jika candidates tinggal satu (fallback url), maka terima apa adanya.
            is_valid = False
            if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                if "project-siesta" not in temp_path:
                    is_valid = True
                elif url == FALLBACK_COVER_URL:
                    # Jika URL fallback pun gagal dan kembali ke siesta, ya sudah terima saja
                    is_valid = True 
            
            if is_valid:
                cover_path = temp_path
                break
        except:
            pass

    if not cover_path:
        LOGGER.warning(f"LivePhish: Gagal total mendapatkan cover art (bahkan fallback).")

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    await edit_message(user['bot_msg'], f"Ditemukan: {artist_name} - {album_name} ({total_tracks} tracks).")

    # --- PERBAIKAN STRUKTUR FOLDER (FIX NAMA ZIP) ---
    # Buat subfolder: ID_PESAN/Nama Artis - Nama Album/
    # Ini agar ZIP nanti bernama "Nama Artis - Nama Album.zip"
    folder_name = f"{artist_name} - {album_name}"
    # Batasi panjang folder agar tidak error OS
    if len(folder_name) > 100: folder_name = folder_name[:100]
    
    base_folder_path = f"{str(user['r_id'])}/{folder_name}/"

    base_meta = {
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': year,
        'cover': cover_path,
        'totaltracks': str(total_tracks),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, # Path baru
        'type': 'album',
        'genre': 'Rock',
        'copyright': 'LivePhish',
        'explicit': False
    }
    
    completed_tracks = []

    for i, t in enumerate(tracks):
        track_id = t.get("trackID") or t.get("songID")
        title = t.get("songTitle", f"Track {i+1}")
        track_num = t.get("trackNum", str(i+1))
        disc_num = t.get("discNum", 1)
        
        # PERBAIKAN DURASI (Pastikan Integer)
        try:
            duration = int(float(t.get("length", 0)))
        except:
            duration = 0
        
        msg_text = f"Mendownload {i+1}/{total_tracks}: {title}"
        await edit_message(user['bot_msg'], msg_text)

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

        # Nama file bersih
        clean_title = sanitize_name(title)
        fname = f"{track_num}. {clean_title}{ext}"
        fpath = base_meta['tempfolder'] + fname

        err = await download_file(stream_url, fpath)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        track_meta = base_meta.copy()
        track_meta.update({
            'title': title,
            'tracknumber': str(track_num),
            'volume': str(disc_num),
            'filepath': fpath,
            'itemid': str(track_id),
            'duration': duration, 
            'extension': ext.replace(".", "")
        })
        
        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    # --- FINALISASI & UPLOAD ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        # Ambil Settings
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

        # 1. Buat ZIP (Nama ZIP akan mengikuti nama folder 'base_meta['folderpath']')
        if album_zip:
            await edit_message(user['bot_msg'], "Membuat file ZIP...")
            # zip_handler biasanya mengambil nama folder terakhir sebagai nama ZIP
            base_meta['zip_path'] = await zip_handler(base_meta['folderpath'])

        # 2. Kirim Art Poster
        if art_poster:
            # Karena sudah ada fallback URL, cover_path harusnya tidak kosong
            if base_meta.get('cover') and os.path.exists(base_meta['cover']):
                try:
                    base_meta['poster_msg'] = await post_art_poster(user, base_meta)
                except Exception as e:
                    LOGGER.error(f"Gagal mengirim Art Poster: {e}")
            else:
                LOGGER.warning("Cover Art tetap tidak ditemukan, Art Poster dilewati.")

        # 3. Upload Album
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
