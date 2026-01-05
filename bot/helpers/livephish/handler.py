# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import aiohttp
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
    year = resp.get("performanceDateYear", "")
    if not year:
        p_date = resp.get("performanceDate") 
        if p_date:
            year = p_date.split("/")[-1]

    # --- PERBAIKAN COVER ART ---
    cover_url = ""
    pics = resp.get("pics", [])
    if pics:
        # Urutkan dari yang terbesar
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        
        # Cari URL yang valid
        for p in pics:
            raw_url = p.get("url", "")
            if not raw_url: continue
            
            # Jika relatif, tambahkan domain www (bukan static)
            if raw_url.startswith("/"):
                cover_url = "https://www.livephish.com" + raw_url
            else:
                cover_url = raw_url
            
            # (Opsional) replace static dengan www jika sering error 410
            cover_url = cover_url.replace("static.livephish.com", "www.livephish.com")
            break

    # Download Cover (Safe Mode)
    try:
        cover_path = await create_cover_file(
            cover_url, 
            {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
        )
        # Cek jika file cover sebenarnya gagal (misal isinya text error)
        # Tapi create_cover_file biasanya sudah handle
    except Exception as e:
        LOGGER.warning(f"Gagal download cover: {e}. Melanjutkan tanpa cover.")
        cover_path = ""

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
        'type': 'album'
    }
    
    completed_tracks = []

    for i, t in enumerate(tracks):
        # --- PERBAIKAN ID TRACK ---
        # Prioritaskan 'trackID' karena itu yang dipakai di kode Go.
        # 'songID' mungkin internal database ID yang berbeda.
        track_id = t.get("trackID") 
        if not track_id:
            track_id = t.get("songID")

        title = t.get("songTitle")
        track_num = t.get("trackNum")
        disc_num = t.get("discNum", 1)
        
        msg_text = f"Mendownload {i+1}/{total_tracks}: {title}"
        await edit_message(user['bot_msg'], msg_text)

        stream_url = await client.get_stream_url(track_id, livephish_manager.quality)

        if not stream_url:
            LOGGER.error(f"Stream URL kosong untuk ID: {track_id} | Title: {title}")
            continue

        ext = ".m4a"
        if livephish_manager.quality == "FLAC" and "flac" in str(stream_url).lower():
            ext = ".flac"
        elif livephish_manager.quality == "FLAC": 
            # Fallback terjadi
            ext = ".m4a" if "m4a" in str(stream_url).lower() else ".mp3"

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
            'itemid': str(track_id)
        })
        
        await set_metadata(track_meta, user['user_id'])
        completed_tracks.append(track_meta)

    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh. Kemungkinan langganan habis atau IP diblokir.")
