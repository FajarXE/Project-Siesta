import os
import re
import asyncio
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata
import yt_dlp 

# --- IMPOR UPLOADER (Sesuai nama file yang anda upload: uploder.py) ---
try:
    from bot.helpers.uploder import track_upload
except ImportError:
    # Fallback jika nama filenya beda
    from bot.helpers.uploader import track_upload

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

def ensure_download_dir(user):
    if 'dir' not in user or not user['dir']:
        uid = user.get('user_id', 'temp_user')
        user['dir'] = os.path.join("downloads", str(uid))
    if not os.path.exists(user['dir']):
        os.makedirs(user['dir'])
    return user['dir']

async def download_with_ytdlp(url, output_path):
    def run_ytdlp():
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    await asyncio.to_thread(run_ytdlp)

async def start_gaana(link: str, user: dict):
    msg = user['bot_msg']
    session = gaana_manager.session
    api = gaana_manager.api

    ensure_download_dir(user)

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link Gaana tidak valid.")
        return

    content_type, identifier = match.groups()

    if content_type == 'song':
        data = await api.get_metadata(session, identifier, 'songDetail')
        if data and 'tracks' in data and data['tracks']:
            await process_gaana_track(data['tracks'][0], user, session, api)
        else:
            await edit_message(msg, "Lagu tidak ditemukan.")

    elif content_type == 'album':
        await edit_message(msg, "Mengambil data Album...")
        data = await api.get_metadata(session, identifier, 'albumDetail')
        
        if not data or 'tracks' not in data:
            await edit_message(msg, "Gagal mengambil data album.")
            return

        tracks = data['tracks']
        total = len(tracks)
        await edit_message(msg, f"Ditemukan {total} lagu. Memulai download...")

        for i, track in enumerate(tracks):
            await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('track_title')}...")
            try:
                await process_gaana_track(track, user, session, api, is_album=True)
            except Exception as e:
                LOGGER.error(f"Gagal download track Gaana {i+1}: {e}")
                
        await edit_message(msg, "Download Album Selesai!")
    
    elif content_type == 'playlist':
        await edit_message(msg, "Playlist belum didukung.")

async def process_gaana_track(track_info, user, session, api, is_album=False):
    msg = user['bot_msg']
    
    try:
        title = track_info.get("track_title", "Unknown")
        
        # 1. Decrypt URL
        enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
        if not enc_path: raise Exception("Stream path tidak ditemukan.")
        decrypted_url = api.decrypt_stream_path(enc_path)
        final_url = decrypted_url.replace("medium.mp4", "high.mp4").replace("low.mp4", "high.mp4")

        # 2. Download (Gunakan ekstensi .m4a)
        filename = f"{sanitize_filename(title)}.m4a" 
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        if os.path.exists(file_path): os.remove(file_path)

        try:
            await download_with_ytdlp(final_url, file_path)
        except Exception as e:
            # Fallback ke URL decrypted biasa jika high quality gagal
            await download_with_ytdlp(decrypted_url, file_path)

        if not os.path.exists(file_path) or os.path.getsize(file_path) < 10000:
             raise Exception("Download gagal atau file korup.")

        # 3. Cover Art
        artwork_url = track_info.get('artwork')
        cover_path = None
        if artwork_url:
            artwork_url = artwork_url.replace('size_s', 'size_l') 
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(artwork_url) as resp:
                     if resp.status == 200:
                        import aiofiles
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        # 4. Metadata
        try:
            await set_gaana_metadata(file_path, track_info, cover_path)
        except Exception as e: pass
        
        # 5. UPLOAD (via uploder.py)
        artists = track_info.get("artist", [])
        artist_name = artists[0]['name'] if artists else "Unknown"

        metadata = {
            'filepath': file_path,
            'title': title,
            'artist': artist_name,
            'album': track_info.get("album_title", "Unknown"),
            'cover': cover_path,
            'provider': 'Gaana',
            'type': 'track'
        }
        
        # Kirim ke task handler uploader Anda
        await track_upload(metadata, user)

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"Gaana Error: {e}")
        if not is_album: raise e
