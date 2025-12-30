import os
import re
import asyncio
import shutil
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata
from bot.helpers.uploder import track_upload, album_upload
from bot import Config
# IMPOR create_simple_text
from bot.helpers.utils import fetch_zip_settings, create_simple_text
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

async def process_single_gaana(track, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengunduh...")
    try:
        path, cover, dur = await download_gaana_track(track, user, session, api)
        metadata = {
            'filepath': path,
            'title': track.get("track_title"),
            'artist': track.get("artist")[0]['name'] if track.get("artist") else "",
            'album': track.get("album_title"),
            'cover': cover, 'provider': 'Gaana', 'type': 'track',
            'duration': dur, 'quality': '320kbps'
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
    album_dir = ensure_download_dir(user, subdir=album_title)
    
    downloaded = []
    total = len(tracks)
    await edit_message(msg, f"Album: {album_title} ({total} tracks)")

    for i, track in enumerate(tracks):
        try:
            track["track_number"] = str(i + 1)
            track["track_count"] = str(total)
            track["label_name"] = data.get("label_name")
            
            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            
            track_num = i + 1
            path, cover, dur = await download_gaana_track(track, user, session, api, custom_dir=album_dir, track_num=track_num)
            
            downloaded.append({
                'filepath': path, 'title': track.get("track_title"),
                'artist': track.get("artist")[0]['name'] if track.get("artist") else "Unknown",
                'album': album_title, 'cover': cover, 'duration': dur,
                'quality': '320kbps'
            })
        except Exception as e:
            LOGGER.error(f"Skip Gaana: {e}")

    await edit_message(msg, "Memproses Album...")
    
    _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
    
    zip_path = None
    if is_album_zip:
         await edit_message(msg, "Membuat ZIP...")
         parent_dir = os.path.dirname(album_dir)
         zip_name = sanitize_filename(album_title)
         base_name = os.path.join(parent_dir, zip_name)
         zip_path = shutil.make_archive(base_name, 'zip', album_dir)

    # --- PREPARE METADATA ---
    metadata = {
        'type': 'album', 'title': album_title,
        'folderpath': album_dir, 'tracks': downloaded,
        'cover': downloaded[0]['cover'] if downloaded else None,
        'zip_path': zip_path, 
        'poster_msg': False, # Manual handling
        'provider': 'Gaana', 
        'release_date': data.get("release_date", ""),
        'track_count': total, 
        'quality': '320kbps'
    }

    # --- MANUAL ART POSTER (CAPTION LENGKAP) ---
    if is_art_poster and metadata['cover'] and os.path.exists(metadata['cover']):
        try:
            caption = await create_simple_text(metadata, user)
            await send_message(user, metadata['cover'], 'pic', caption=caption)
        except Exception as e:
            LOGGER.error(f"Gagal kirim poster Gaana: {e}")
    # -------------------------------------------

    await album_upload(metadata, user)

async def download_gaana_track(track_info, user, session, api, custom_dir=None, track_num=None):
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

    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    
    clean_title = sanitize_filename(title)
    if track_num:
        filename = f"{track_num:02d}. {clean_title}.m4a"
    else:
        filename = f"{clean_title}.m4a"
        
    path = os.path.join(dl_dir, filename)
    
    if os.path.exists(path): os.remove(path)
    
    try:
        await download_with_ytdlp(final_url, path)
    except: pass
    
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
         await download_with_ytdlp(decrypted_url, path)

    if not os.path.exists(path): raise Exception("Fail DL")

    artwork_url = track_info.get('artwork', '').replace('size_s', 'size_l')
    cover_path = os.path.join(dl_dir, "cover.jpg")
    if artwork_url and not os.path.exists(cover_path):
        async with session.get(artwork_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                     await f.write(await resp.read())
    
    dur = await set_gaana_metadata(path, track_info, cover_path)
    return path, cover_path, dur
