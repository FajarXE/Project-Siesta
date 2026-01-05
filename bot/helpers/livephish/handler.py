# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import os
import aiohttp
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

# Import Utils & Uploder
from bot.helpers.utils import download_file, create_zip, create_art_poster
from bot.helpers.uploder import track_upload, album_upload 

# Import Settings untuk cek status ZIP/Poster
from bot.settings import bot_set

from bot.helpers.message import edit_message
from bot.logger import LOGGER

ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

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

    album_name = resp.get("containerInfo", "Unknown Album")
    artist_name = resp.get("artistName", "Phish")
    
    year = str(resp.get("performanceDateYear", ""))
    if not year:
        p_date = resp.get("performanceDate") 
        if p_date:
            year = p_date.split("/")[-1]

    # --- LOGIKA COVER ART ---
    cover_path = ""
    pics = resp.get("pics", [])
    
    if pics:
        # Sortir: Lebar terbesar dulu
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        
        for i, p in enumerate(pics):
            raw_url = p.get("url", "")
            if not raw_url: continue
            
            # Coba konstruksi URL
            candidates = []
            if raw_url.startswith("/"):
                # Prioritaskan www.livephish.com
                candidates.append("https://www.livephish.com" + raw_url)
            else:
                candidates.append(raw_url)
                if "static.livephish.com" in raw_url:
                    candidates.append(raw_url.replace("static.livephish.com", "www.livephish.com"))

            success = False
            for url in candidates:
                try:
                    # Gunakan create_cover_file
                    temp_path = await create_cover_file(
                        url, 
                        {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
                    )
                    
                    # Validasi: File ada, size > 0, dan bukan fallback image default
                    if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                        if "project-siesta" not in temp_path:
                            cover_path = temp_path
                            success = True
                            break
                except:
                    pass
            
            if success:
                break

    if not cover_path:
        LOGGER.warning(f"LivePhish: Gagal mendapatkan cover art valid untuk ID {album_id}.")

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    await edit_message(user['bot_msg'], f"Ditemukan: {artist_name} - {album_name} ({total_tracks} tracks).")

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
        'tempfolder': str(user['r_id']) + "/",
        'type': 'album',
        'genre': 'Rock',
        'copyright': 'LivePhish',
        'explicit': False
    }
    
    completed_tracks = []

    for i, t in enumerate(tracks):
        track_id = t.get("trackID") or t.get("songID")
        title = t.get("songTitle")
        track_num = t.get("trackNum")
        disc_num = t.get("discNum", 1)
        
        # PERBAIKAN DURASI: Konversi ke Int (Detik)
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

        fname = f"{track_num}. {title}{ext}".replace("/", "_")
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
            'duration': duration, # Pastikan ini INT
            'extension': ext.replace(".", "")
        })
        
        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    # --- LOGIKA ZIP & ART POSTER (DITAMBAHKAN) ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        # 1. Cek & Buat ZIP
        if bot_set.album_zip:
            await edit_message(user['bot_msg'], "Membuat file ZIP...")
            try:
                # create_zip biasanya mengembalikan path zip
                zip_path = await create_zip(base_meta)
                if zip_path:
                    base_meta['zip_path'] = zip_path
            except Exception as e:
                LOGGER.error(f"Gagal membuat ZIP: {e}")

        # 2. Cek & Buat Art Poster
        if bot_set.art_poster:
            await edit_message(user['bot_msg'], "Membuat Art Poster...")
            try:
                # create_art_poster biasanya mengembalikan path poster
                poster_path = await create_art_poster(base_meta)
                if poster_path:
                    base_meta['poster_path'] = poster_path
            except Exception as e:
                LOGGER.error(f"Gagal membuat Art Poster: {e}")

        # 3. Upload
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
