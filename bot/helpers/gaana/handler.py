import os
import re
import shutil
import asyncio
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata
from bot.helpers.uploder import track_upload, album_upload
import yt_dlp 

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

def ensure_download_dir(user, subdir=None):
    uid = user.get('user_id', 'temp_user')
    base = os.path.join("downloads", str(uid))
    if subdir:
        base = os.path.join(base, sanitize_filename(subdir))
    if not os.path.exists(base):
        os.makedirs(base)
    return base

async def download_with_ytdlp(url, output_path):
    def run_ytdlp():
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True, 'no_warnings': True, 'nocheckcertificate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
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
        path, cover = await download_gaana_track(track, user, session, api)
        metadata = {
            'filepath': path,
            'title': track.get("track_title"),
            'artist': track.get("artist")[0]['name'] if track.get("artist") else "",
            'album': track.get("album_title"),
            'cover': cover, 'provider': 'Gaana', 'type': 'track'
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
            await edit_message(msg, f"[{i+1}/{total}] {track.get('track_title')}...")
            path, cover = await download_gaana_track(track, user, session, api, custom_dir=album_dir)
            downloaded.append({
                'filepath': path, 'title': track.get("track_title"),
                'artist': track.get("artist")[0]['name'], 'album': album_title,
                'cover': cover
            })
        except Exception as e:
            LOGGER.error(f"Skip Gaana: {e}")

    # ZIP & Poster Logic
    await edit_message(msg, "Memproses Album...")
    zip_path = None
    should_zip = user.get('zip', False) or user.get('zip_mode', False)
    
    if should_zip:
         await edit_message(msg, "Membuat ZIP...")
         zip_base = os.path.join(ensure_download_dir(user), sanitize_filename(album_title))
         zip_path = shutil.make_archive(zip_base, 'zip', album_dir)

    metadata = {
        'type': 'album', 'title': album_title,
        'folderpath': album_dir, 'tracks': downloaded,
        'cover': downloaded[0]['cover'] if downloaded else None,
        'zip_path': zip_path,
        'poster_msg': user.get('poster', False) or user.get('art_poster', False),
        'provider': 'Gaana'
    }
    await album_upload(metadata, user)

async def download_gaana_track(track_info, user, session, api, custom_dir=None):
    title = track_info.get("track_title")
    enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
    if not enc_path: raise Exception("No stream")
    
    decrypted_url = api.decrypt_stream_path(enc_path)
    
    # FIX QUALITY 320KBPS (Sesuai referensi gaana.py: replace .mp4 -> _320.mp4 atau semacamnya)
    # Tapi yt-dlp lebih pintar menangani manifest. Kita gunakan high quality replacement jika m3u8.
    # Jika decrypted url adalah mp4 langsung (progressive), kita ubah bitratenya.
    # Gaana pattern: .../medium.mp4 or .../128.mp4
    # Kita coba paksa ke high/320.
    final_url = decrypted_url.replace("medium.mp4", "high.mp4") \
                             .replace("128.mp4", "320.mp4") \
                             .replace("64.mp4", "320.mp4")
                             
    # Download
    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    filename = f"{sanitize_filename(title)}.m4a"
    path = os.path.join(dl_dir, filename)
    
    if os.path.exists(path): os.remove(path)
    
    # Gunakan YT-DLP (Paling stabil untuk Gaana HLS/M3U8)
    await download_with_ytdlp(final_url, path)
    
    # Fallback jika gagal high quality
    if not os.path.exists(path) or os.path.getsize(path) < 10000:
         await download_with_ytdlp(decrypted_url, path)

    if not os.path.exists(path): raise Exception("Fail DL")

    # Cover
    artwork_url = track_info.get('artwork', '').replace('size_s', 'size_l')
    cover_path = os.path.join(dl_dir, "cover.jpg")
    if artwork_url and not os.path.exists(cover_path):
        async with session.get(artwork_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                     await f.write(await resp.read())
    
    await set_gaana_metadata(path, track_info, cover_path)
    return path, cover_path
