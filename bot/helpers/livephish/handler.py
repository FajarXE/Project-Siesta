# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file
from bot.helpers.utils import download_file, track_upload, album_upload
from bot.helpers.message import edit_message
from bot.logger import LOGGER

# REGEX BARU: Mendukung format URL lama dan format URL 'show.aspx?show=123'
ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

async def start_livephish(link: str, user: dict):
    client = user.get('livephish_api')
    if not client:
        raise Exception("Internal Error: LivePhish Client not passed.")

    # 1. Extract ID
    match = ID_REGEX.search(link)
    if not match:
        raise Exception(f"Gagal mengekstrak Album ID dari link: {link}")
    album_id = match.group(1)

    await edit_message(user['bot_msg'], f"Mengambil metadata ID: {album_id}...")
    
    # 2. Get Metadata
    meta_json = await client.get_album_meta(album_id)
    resp = meta_json.get("Response", {})
    
    if not resp:
        # Coba periksa apakah error dari API
        err_msg = meta_json.get("ResponseStatus", {}).get("message", "Response kosong")
        raise Exception(f"Gagal mengambil metadata (ID: {album_id}): {err_msg}")

    album_name = resp.get("containerInfo", "Unknown Album")
    artist_name = resp.get("artistName", "Phish")
    year = resp.get("performanceDateYear", "")
    if not year:
        # Fallback date parsing
        p_date = resp.get("performanceDate") # e.g. 1/3/2003
        if p_date:
            year = p_date.split("/")[-1]

    # Cover Art
    cover_url = ""
    # Cari gambar resolusi tinggi dari array pics
    pics = resp.get("pics", [])
    if pics:
        # Sort by width desc
        pics.sort(key=lambda x: x.get("width", 0), reverse=True)
        cover_url = pics[0].get("url", "")
    
    # Download Cover
    cover_path = await create_cover_file(cover_url, {"itemid": album_id, "tempfolder": user['r_id'] + "/"})

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)

    await edit_message(user['bot_msg'], f"Ditemukan: {artist_name} - {album_name} ({total_tracks} tracks).")

    # 3. Process Tracks
    base_meta = {
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': year,
        'cover': cover_path,
        'totaltracks': str(total_tracks),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality, # FLAC/ALAC/AAC
        'tempfolder': user['r_id'] + "/",
        'type': 'album'
    }
    
    completed_tracks = []

    for i, t in enumerate(tracks):
        track_id = t.get("songID") # atau trackID
        if not track_id:
            track_id = t.get("trackID")

        title = t.get("songTitle")
        track_num = t.get("trackNum")
        disc_num = t.get("discNum", 1)
        
        msg_text = f"Mendownload {i+1}/{total_tracks}: {title}"
        await edit_message(user['bot_msg'], msg_text)

        # Get Stream
        # Gunakan kualitas global dari manager
        stream_url = await client.get_stream_url(track_id, livephish_manager.quality)
        
        if not stream_url:
            LOGGER.error(f"LivePhish: Gagal dapat stream URL untuk {title}")
            continue

        # Tentukan ekstensi
        ext = ".m4a"
        if livephish_manager.quality == "FLAC":
            ext = ".flac"
        elif livephish_manager.quality == "ALAC":
            ext = ".m4a" # ALAC juga m4a

        fname = f"{track_num}. {title}{ext}".replace("/", "_")
        fpath = base_meta['tempfolder'] + fname

        # Download
        err = await download_file(stream_url, fpath)
        if err:
            LOGGER.error(f"Download error {title}: {err}")
            continue

        # Tagging
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

    # 4. Upload
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")
