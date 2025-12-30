import os
import re
import asyncio
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata
import yt_dlp

# --- IMPOR UPLOADER ---
try:
    from bot.helpers.uploder import track_upload
except ImportError:
    from bot.helpers.uploader import track_upload

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album)/.+?/(.+)")

def ensure_download_dir(user):
    if 'dir' not in user or not user['dir']:
        uid = user.get('user_id', 'temp_user')
        user['dir'] = os.path.join("downloads", str(uid))
    if not os.path.exists(user['dir']):
        os.makedirs(user['dir'])
    return user['dir']

async def download_jiosaavn_ytdlp(url, output_path):
    def run_ytdlp():
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'geo_bypass': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    
    await asyncio.to_thread(run_ytdlp)

async def start_jiosaavn(link: str, user: dict):
    msg = user['bot_msg']
    session = jiosaavn_manager.session
    api = jiosaavn_manager.api
    
    ensure_download_dir(user)

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link JioSaavn tidak valid.")
        return

    kind, token_id = match.groups()
    
    if kind == 'song':
        await process_track(token_id, user, session, api)
    elif kind == 'album':
        await edit_message(msg, "Mengambil data Album...")
        album_data = await api.get_album_details(session, token_id)
        
        tracks = []
        if album_data:
            if 'list' in album_data: tracks = album_data['list']
            elif 'songs' in album_data: tracks = album_data['songs']
        
        if not tracks:
            await edit_message(msg, "Album kosong atau gagal diambil.")
            return

        total = len(tracks)
        await edit_message(msg, f"Ditemukan {total} lagu. Memulai download...")
        
        for i, track in enumerate(tracks):
            try:
                song_token = None
                target_link = None
                
                if 'perma_url' in track:
                    target_link = track['perma_url']
                    song_token = target_link.split('/')[-1]
                elif 'url' in track:
                    song_token = track['url'].split('/')[-1]
                
                if not song_token: continue

                await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('song', 'Unknown')}...")
                await process_track(song_token, user, session, api, is_album=True, link_override=target_link)
                
            except Exception as e:
                LOGGER.error(f"Gagal download track JioSaavn {i+1}: {e}")
                
        await edit_message(msg, "Download Album Selesai!")

async def process_track(token_id, user, session, api, is_album=False, link_override=None):
    msg = user['bot_msg']
    if not is_album:
        await edit_message(msg, "Mengambil info lagu...")

    try:
        track_data = await api.get_song_details(session, token_id)
        if not track_data:
             raise Exception("Metadata lagu tidak ditemukan.")

        title = track_data.get("song")
        image_url = track_data.get("image", "").replace("150x150", "500x500")
        perma_url = track_data.get("perma_url")

        dl_target = link_override if link_override else perma_url
        if not dl_target: raise Exception("Link lagu tidak ditemukan.")

        filename = f"{sanitize_filename(title)}.m4a"
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        if os.path.exists(file_path): os.remove(file_path)

        try:
            await download_jiosaavn_ytdlp(dl_target, file_path)
        except Exception as e:
            raise Exception(f"yt-dlp gagal: {e}")

        if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
             raise Exception("File gagal didownload (Kosong/404).")

        # Download Cover
        cover_path = None
        if image_url:
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        import aiofiles
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        try:
             await set_jiosaavn_metadata(file_path, track_data, cover_path)
        except: pass

        # UPLOAD (via uploder.py)
        if not is_album:
             await edit_message(msg, "Mengunggah...")
             
        metadata = {
            'filepath': file_path,
            'title': title,
            'artist': track_data.get("primary_artists", "Unknown"),
            'album': track_data.get("album", "Unknown"),
            'cover': cover_path,
            'provider': 'JioSaavn',
            'type': 'track'
        }
        
        await track_upload(metadata, user)

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"JioSaavn Error: {e}")
        if not is_album: raise e
