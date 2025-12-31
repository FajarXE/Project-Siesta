import os
import re
import asyncio
import shutil
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata
from bot.helpers.uploder import track_upload, album_upload, playlist_upload
from bot import Config
from bot.helpers.utils import fetch_zip_settings
import yt_dlp 

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

def ensure_download_dir(user, subdir=None):
    base_dir = Config.DOWNLOAD_BASE_DIR
    uid = user.get('user_id', 'temp')
    user_dir = os.path.join(base_dir, str(uid))
    if subdir:
        user_dir = os.path.join(user_dir, sanitize_filename(subdir))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

async def download_with_ytdlp(url, output_path):
    def run_ytdlp():
        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': output_path, 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
    await asyncio.to_thread(run_ytdlp)

async def start_gaana(link: str, user: dict):
    msg = user['bot_msg']
    session = gaana_manager.session
    api = gaana_manager.api

    match = URL_REGEX.search(link)
    if not match: return

    content_type, identifier = match.groups()
    if content_type == 'song':
        data = await api.get_metadata(session, identifier, 'songDetail')
        if data and 'tracks' in data:
            await process_single_gaana(data['tracks'][0], user, session, api)
    elif content_type == 'album':
        await process_album_gaana(identifier, user, session, api)
    elif content_type == 'playlist':
        await process_playlist_gaana(identifier, user, session, api)

async def process_single_gaana(track, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengunduh...")
    try:
        # Single track tidak butuh playlist_index
        path, cover, dur = await download_gaana_track(track, user, session, api)
        
        metadata = {
            'filepath': path, 'title': track.get("track_title"),
            'artist': track.get("artist")[0]['name'] if track.get("artist") else "",
            'album': track.get("album_title"), 'cover': cover, 'provider': 'Gaana', 
            'type': 'track', 'duration': dur, 'quality': '320kbps'
        }
        await track_upload(metadata, user)
        await edit_message(msg, "Selesai!")
    except Exception as e:
        await edit_message(msg, f"Error: {e}")

async def process_album_gaana(identifier, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil data Album...")
    data = await api.get_metadata(session, identifier, 'albumDetail')
    
    if not data or 'tracks' not in data:
        await edit_message(msg, "Album gagal.")
        return

    tracks = data['tracks']
    album_title = data.get("title") or tracks[0].get("album_title")
    dl_dir = ensure_download_dir(user, subdir=album_title)
    
    downloaded = []
    total = len(tracks)
    is_explicit = "False"

    await edit_message(msg, f"Album: {album_title} ({total} tracks)")

    for i, track in enumerate(tracks):
        try:
            # Metadata Album Asli
            track["track_count"] = str(total)
            track["label_name"] = data.get("label_name")
            if track.get("parental_warning") == 1: is_explicit = "True"

            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            
            # Album: Playlist Index = i+1 agar file urut
            path, cover, dur = await download_gaana_track(track, user, session, api, custom_dir=dl_dir, playlist_index=i+1)
            
            downloaded.append({
                'filepath': path, 'title': track.get("track_title"),
                'artist': track.get("artist")[0]['name'] if track.get("artist") else "Unknown",
                'album': album_title, 'cover': cover, 'duration': dur, 'quality': '320kbps'
            })
        except Exception as e:
            LOGGER.error(f"Skip Gaana: {e}")

    await edit_message(msg, "Memproses Album...")
    _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
    
    zip_path = None
    if is_album_zip:
         await edit_message(msg, "Membuat ZIP...")
         parent_dir = os.path.dirname(dl_dir)
         zip_name = sanitize_filename(album_title)
         base_name = os.path.join(parent_dir, zip_name)
         zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

    release_date = data.get("release_date")
    if not release_date: release_date = tracks[0].get("release_date", "Unknown")

    if is_art_poster and downloaded:
        cover_file = downloaded[0]['cover']
        if cover_file and os.path.exists(cover_file):
            try:
                caption = (
                    f"**ᴛɪᴛʟᴇ :** {album_title}\n**ᴀʀᴛɪsᴛ :** {downloaded[0]['artist']}\n"
                    f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                    f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                    f"**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
                )
                await send_message(user, cover_file, 'pic', caption=caption)
            except: pass

    metadata = {
        'type': 'album', 'title': album_title, 'folderpath': dl_dir, 
        'tracks': downloaded, 'cover': downloaded[0]['cover'] if downloaded else None,
        'zip_path': zip_path, 'poster_msg': False, 'provider': 'Gaana', 
        'release_date': release_date, 'track_count': total, 'quality': '320kbps'
    }
    await album_upload(metadata, user)

async def process_playlist_gaana(identifier, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil data Playlist...")
    data = await api.get_metadata(session, identifier, 'playlistDetail')
    
    if not data or 'tracks' not in data:
        await edit_message(msg, "Playlist gagal.")
        return

    tracks = data['tracks']
    
    # --- JUDUL: Hapus "Gaana Dj" ---
    title = data.get("title") or data.get("english_title") or data.get("name") or "Unknown Playlist"
    title = title.replace("&amp;", "&")
    title = re.sub(r'(?i)gaana\s*dj\s*', '', title).strip() # Hapus kata Gaana Dj
    
    # Jika hasil hapus jadi kosong (misal judul aslinya cuma "Gaana DJ"), ambil slug URL
    if not title:
        title = identifier.replace("-", " ").title()
        title = re.sub(r'(?i)gaana\s*dj\s*', '', title).strip()
    # -------------------------------
    
    dl_dir = ensure_download_dir(user, subdir=title)
    
    # --- COVER PLAYLIST SPESIFIK ---
    # Kita download ke 'playlist_cover_final.jpg' agar tidak tertimpa
    playlist_artwork = data.get("artwork_large") or data.get("artwork_web") or data.get("artwork")
    
    playlist_cover_path = os.path.join(dl_dir, "playlist_cover_final.jpg")
    playlist_cover_exists = False

    if playlist_artwork:
        # Bersihkan URL
        hq_artwork = re.sub(r'crop_\d+x\d+_', '', playlist_artwork)
        hq_artwork = hq_artwork.replace("size_s", "size_xl").replace("size_m", "size_xl")
        
        try:
            async with session.get(hq_artwork) as resp:
                if resp.status == 200:
                    async with aiofiles.open(playlist_cover_path, mode='wb') as f:
                        await f.write(await resp.read())
                    playlist_cover_exists = True
        except: pass
        
        # Fallback ke original URL jika hq gagal
        if not playlist_cover_exists:
            try:
                async with session.get(playlist_artwork) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(playlist_cover_path, mode='wb') as f:
                            await f.write(await resp.read())
                        playlist_cover_exists = True
            except: pass
    
    # Jika gagal total, set path ke None
    if not playlist_cover_exists: playlist_cover_path = None
    # -------------------------------

    downloaded = []
    total = len(tracks)
    is_explicit = "False"

    await edit_message(msg, f"Playlist: {title} ({total} tracks)")

    for i, track in enumerate(tracks):
        try:
            if track.get("parental_warning") == 1: is_explicit = "True"

            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            
            # PENTING: Pass i+1 sebagai playlist_index untuk nama file
            # TAPI JANGAN ubah metadata track['track_number'] disini jika ingin nomor asli
            path, cover, dur = await download_gaana_track(
                track, user, session, api, custom_dir=dl_dir, playlist_index=i+1
            )
            
            downloaded.append({
                'filepath': path, 'title': track.get("track_title"),
                'artist': track.get("artist")[0]['name'] if track.get("artist") else "Unknown",
                'album': title, 'cover': cover, 'duration': dur, 'quality': '320kbps'
            })
        except Exception as e:
            LOGGER.error(f"Skip Gaana: {e}")

    await edit_message(msg, "Memproses Playlist...")
    
    is_pl_zip, _, _, is_art_poster = fetch_zip_settings(user)
    
    zip_path = None
    if is_pl_zip:
         await edit_message(msg, "Membuat ZIP...")
         parent_dir = os.path.dirname(dl_dir)
         zip_name = sanitize_filename(title)
         base_name = os.path.join(parent_dir, zip_name)
         zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

    # Gunakan cover playlist yang benar untuk poster
    poster_img = playlist_cover_path if playlist_cover_exists else (downloaded[0]['cover'] if downloaded else None)

    if is_art_poster and poster_img:
        try:
            caption = (
                f"**ᴛɪᴛʟᴇ :** {title}\n**ᴛʏᴘᴇ :** Playlist\n"
                f"**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n"
                f"**ǫᴜᴀʟɪᴛʏ :** 320kbps\n**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
            )
            await send_message(user, poster_img, 'pic', caption=caption)
        except: pass

    metadata = {
        'type': 'playlist', 'title': title, 'folderpath': dl_dir, 
        'tracks': downloaded, 'cover': poster_img, 
        'zip_path': zip_path, 'poster_msg': False, 'provider': 'Gaana', 
        'track_count': total, 'quality': '320kbps'
    }
    await playlist_upload(metadata, user)

async def download_gaana_track(track_info, user, session, api, custom_dir=None, playlist_index=None):
    title = track_info.get("track_title")
    enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
    if not enc_path: raise Exception("No stream")
    
    decrypted_url = api.decrypt_stream_path(enc_path)
    final_url = decrypted_url
    if "medium.mp4" in final_url: final_url = final_url.replace("medium.mp4", "320.mp4")
    elif "128.mp4" in final_url: final_url = final_url.replace("128.mp4", "320.mp4")
    elif "f.mp4" in final_url: final_url = final_url.replace("f.mp4", "320.mp4")
    elif "64.mp4" in final_url: final_url = final_url.replace("64.mp4", "320.mp4")
    elif "low.mp4" in final_url: final_url = final_url.replace("low.mp4", "320.mp4")
    else: final_url = final_url.replace(".mp4", "_320.mp4")

    # --- NAMA FILE vs METADATA ---
    # Gunakan playlist_index untuk nama file agar urut (1 - Title, 2 - Title)
    # Tapi JANGAN ubah track_info['track_number'] agar metadata tetap asli
    safe_title = sanitize_filename(title)
    
    if playlist_index:
        filename = f"{int(playlist_index)} - {safe_title}.m4a"
    else:
        # Jika single/album, gunakan track number asli jika ada
        t_num = track_info.get('track_number')
        if t_num:
            filename = f"{int(t_num)} - {safe_title}.m4a"
        else:
            filename = f"{safe_title}.m4a"

    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    path = os.path.join(dl_dir, filename)
    
    if os.path.exists(path): os.remove(path)
    try:
        await download_with_ytdlp(final_url, path)
    except: pass
    
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
         await download_with_ytdlp(decrypted_url, path)

    if not os.path.exists(path): raise Exception("Fail DL")

    # --- COVER UNIK PER LAGU (PENTING!) ---
    # Kita beri nama cover berdasarkan ID lagu agar tidak saling timpa
    artwork_url = track_info.get('artwork', '')
    if artwork_url:
        artwork_url = re.sub(r'crop_\d+x\d+_', '', artwork_url)
        artwork_url = artwork_url.replace("size_s", "size_xl").replace("size_m", "size_xl")

    # Nama file cover unik: cover_trackID.jpg
    track_id = track_info.get("track_id", "unknown")
    cover_filename = f"cover_{track_id}.jpg"
    cover_path = os.path.join(dl_dir, cover_filename)
    
    if artwork_url and not os.path.exists(cover_path):
        async with session.get(artwork_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                     await f.write(await resp.read())
    
    dur = await set_gaana_metadata(path, track_info, cover_path)
    
    # Hapus cover spesifik lagu ini setelah tagging agar hemat space
    # (Opsional, tapi bagus untuk kebersihan)
    if os.path.exists(cover_path):
        try: os.remove(cover_path)
        except: pass
        
    return path, cover_path, dur
