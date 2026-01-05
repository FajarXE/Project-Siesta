import re
import aiohttp
import os
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

from bot.helpers.utils import download_file
from bot.helpers.uploder import track_upload, album_upload 
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

    # --- LOGIKA BARU DOWNLOAD COVER (DIPERBAIKI) ---
    cover_path = ""
    pics = resp.get("pics", [])
    
    if pics:
        # Urutkan dari resolusi terbesar ke terkecil
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        
        # Coba satu per satu sampai berhasil
        for i, p in enumerate(pics):
            raw_url = p.get("url", "")
            if not raw_url: continue
            
            # Konstruksi URL lengkap
            if raw_url.startswith("/"):
                # Coba domain utama
                candidate_url = "https://www.livephish.com" + raw_url
            else:
                candidate_url = raw_url

            try:
                # Coba download
                temp_path = await create_cover_file(
                    candidate_url, 
                    {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
                )
                
                # FIX KRUSIAL: Cek jika create_cover_file mengembalikan fallback default ('project-siesta')
                # Jika iya, berarti download gagal (404/410), jadi kita harus lanjut loop (continue)
                if "project-siesta" in temp_path:
                    LOGGER.warning(f"LivePhish: Cover #{i+1} gagal/mati ({candidate_url}). Mencoba gambar berikutnya...")
                    continue

                # Verifikasi file ada dan ukurannya valid (>0 bytes)
                if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    cover_path = temp_path
                    LOGGER.info(f"LivePhish: Berhasil download cover (Percobaan #{i+1}): {candidate_url}")
                    break # Berhenti jika sudah berhasil dapat cover asli
                
            except Exception as e:
                LOGGER.warning(f"LivePhish: Error download cover #{i+1}: {e}")
                continue
    
    if not cover_path:
        LOGGER.warning("LivePhish: Tidak ada cover art yang berhasil diunduh dari daftar 'pics'.")

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
        duration = t.get("length", 0)
        
        msg_text = f"Mendownload {i+1}/{total_tracks}: {title}"
        await edit_message(user['bot_msg'], msg_text)

        stream_url = await client.get_stream_url(track_id, livephish_manager.quality)

        if not stream_url:
            LOGGER.error(f"Stream URL kosong untuk: {title}")
            continue

        ext = ".m4a"
        s_url_lower = str(stream_url).lower()
        if "flac" in s_url_lower:
            ext = ".flac"
        elif "mp3" in s_url_lower:
            ext = ".mp3"
        elif livephish_manager.quality == "FLAC":
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
            'duration': str(duration),
            'extension': ext.replace(".", "")
        })
        
        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
