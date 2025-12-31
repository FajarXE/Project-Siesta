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

# Fungsi bantu untuk direct download (Jauh lebih cepat dari yt-dlp)
async def direct_download(session, url, path):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(path, mode='wb') as f:
                    await f.write(await resp.read())
                return True
    except:
        pass
    return False

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
        track['track_number'] = 1
        track['track_count'] = 1
        
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
            if not track.get("track_number"):
                track["track_number"] = str(i + 1)
            
            track["track_count"] = str(total)
            track["label_name"] = data.get("label_name")
            if track.get("parental_warning") == 1: is_explicit = "True"

            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            path, cover, dur = await download_gaana_track(track, user, session, api, custom_dir=dl_dir)
            
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
    
    final_cover_path = None
    if downloaded and downloaded[0].get('cover'):
        final_cover_path = downloaded[0]['cover']

    if is_album_zip:
         await edit_message(msg, "Membersihkan & Membuat ZIP...")
         
         # Cleanup Album: Sisakan 1 cover.jpg
         if final_cover_path and os.path.exists(final_cover_path):
             clean_cover = os.path.join(dl_dir, "cover.jpg")
             try:
                shutil.copy(final_cover_path, clean_cover)
                final_cover_path = clean_cover
             except: pass
         
         for f in os.listdir(dl_dir):
             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                 if f != "cover.jpg":
                     try: os.remove(os.path.join(dl_dir, f))
                     except: pass

         parent_dir = os.path.dirname(dl_dir)
         zip_name = sanitize_filename(album_title)
         base_name = os.path.join(parent_dir, zip_name)
         zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

    release_date = data.get("release_date")
    if not release_date: release_date = tracks[0].get("release_date", "Unknown")

    if is_art_poster and final_cover_path and os.path.exists(final_cover_path):
        try:
            caption = (
                f"**ᴛɪᴛʟᴇ :** {album_title}\n**ᴀʀᴛɪsᴛ :** {downloaded[0]['artist']}\n"
                f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                f"**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
            )
            await send_message(user, final_cover_path, 'pic', caption=caption)
        except: pass

    metadata = {
        'type': 'album', 'title': album_title, 'folderpath': dl_dir, 
        'tracks': downloaded, 'cover': final_cover_path,
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
    
    title_candidates = [data.get("title"), data.get("name"), data.get("playlist_title"), data.get("english_title")]
    valid_titles = [t for t in title_candidates if t and str(t).strip()]
    title = valid_titles[0] if valid_titles else "Unknown Playlist"
    
    clean_identifier = identifier.replace("-", " ").title()
    if "Unknown" in title or title.lower() == identifier.lower(): title = clean_identifier
    title = re.sub(r'(?i)gaana\s*dj\s*', '', title).strip().replace("&amp;", "&")
    if not title: title = clean_identifier
    
    dl_dir = ensure_download_dir(user, subdir=title)
    downloaded = []
    total = len(tracks)

    await edit_message(msg, f"Playlist: {title} ({total} tracks)")

    for i, track in enumerate(tracks):
        try:
            track["track_number"] = str(i + 1)
            track["track_count"] = str(total)

            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            
            path, cover, dur = await download_gaana_track(track, user, session, api, custom_dir=dl_dir)
            
            downloaded.append({
                'filepath': path, 'title': track.get("track_title"),
                'artist': track.get("artist")[0]['name'] if track.get("artist") else "Unknown",
                'album': title, 
                'cover': cover, 
                'duration': dur, 'quality': '320kbps'
            })
        except Exception as e:
            LOGGER.error(f"Skip Gaana: {e}")

    await edit_message(msg, "Memproses Playlist...")
    
    is_pl_zip, _, _, is_art_poster = fetch_zip_settings(user)
    
    siesta_jpg = "project-siesta.jpg"
    siesta_png = "project-siesta.png"
    poster_img = None
    if os.path.exists(siesta_jpg): poster_img = siesta_jpg
    elif os.path.exists(siesta_png): poster_img = siesta_png
    
    if is_pl_zip:
         await edit_message(msg, "Membersihkan & Membuat ZIP...")
         # Cleanup Playlist: Hanya sisakan project-siesta
         for f in os.listdir(dl_dir):
             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                 try: os.remove(os.path.join(dl_dir, f))
                 except: pass
         
         if poster_img:
             try: shutil.copy(poster_img, os.path.join(dl_dir, "project-siesta.jpg"))
             except: pass

         parent_dir = os.path.dirname(dl_dir)
         zip_name = sanitize_filename(title)
         base_name = os.path.join(parent_dir, zip_name)
         zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

    if is_art_poster and poster_img:
        try:
            caption = (
                f"**ᴛɪᴛʟᴇ :** {title}\n"
                f"**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                f"**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                f"**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana"
            )
            await send_message(user, poster_img, 'pic', caption=caption)
        except Exception as e:
            LOGGER.error(f"Gagal kirim art poster playlist: {e}")

    metadata = {
        'type': 'playlist', 'title': title, 'folderpath': dl_dir, 
        'tracks': downloaded, 'cover': poster_img, 
        'zip_path': zip_path, 'poster_msg': False, 'provider': 'Gaana', 
        'track_count': total, 'quality': '320kbps'
    }
    await playlist_upload(metadata, user)

async def download_gaana_track(track_info, user, session, api, custom_dir=None):
    title = track_info.get("track_title")
    enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
    if not enc_path: raise Exception("No stream")
    
    # 1. Dapatkan URL asli hasil dekripsi
    decrypted_url = api.decrypt_stream_path(enc_path)
    
    # 2. Buat URL tebakan kualitas tinggi (320kbps)
    final_url = decrypted_url
    if "medium.mp4" in final_url: final_url = final_url.replace("medium.mp4", "320.mp4")
    elif "128.mp4" in final_url: final_url = final_url.replace("128.mp4", "320.mp4")
    elif "f.mp4" in final_url: final_url = final_url.replace("f.mp4", "320.mp4")
    elif "64.mp4" in final_url: final_url = final_url.replace("64.mp4", "320.mp4")
    elif "low.mp4" in final_url: final_url = final_url.replace("low.mp4", "320.mp4")
    else: final_url = final_url.replace(".mp4", "_320.mp4")

    track_num = track_info.get('track_number')
    safe_title = sanitize_filename(title)
    if track_num: 
        filename = f"{int(track_num)} - {safe_title}.m4a"
    else: 
        filename = f"{safe_title}.m4a"

    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    path = os.path.join(dl_dir, filename)
    
    if os.path.exists(path): os.remove(path)

    # --- OPTIMASI SPEED: Direct Download via aiohttp ---
    # Coba link 320kbps dulu
    downloaded = await direct_download(session, final_url, path)
    
    # Jika gagal atau file kekecilan (kurang dari 10KB), coba link asli (decrypted)
    if not downloaded or os.path.getsize(path) < 10000:
        downloaded = await direct_download(session, decrypted_url, path)

    # Fallback terakhir ke yt-dlp jika direct download masih gagal (misal stream m3u8)
    if not downloaded or os.path.getsize(path) < 10000:
        try:
            await download_with_ytdlp(decrypted_url, path)
        except: pass

    if not os.path.exists(path) or os.path.getsize(path) < 10000: 
        raise Exception("Fail DL")
    # ---------------------------------------------------

    artwork_url = track_info.get('artwork', '')
    if artwork_url:
        artwork_url = re.sub(r'crop_\d+x\d+_', '', artwork_url)
        artwork_url = artwork_url.replace("size_s", "size_xl").replace("size_m", "size_xl")

    cover_filename = f"{safe_title}.jpg"
    cover_path = os.path.join(dl_dir, cover_filename)
    
    if artwork_url and not os.path.exists(cover_path):
        async with session.get(artwork_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                     await f.write(await resp.read())
    
    dur = await set_gaana_metadata(path, track_info, cover_path)
    return path, cover_path, dur
