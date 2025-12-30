import os
import re
import shutil
import aiohttp
import aiofiles
import asyncio
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata
from bot.helpers.uploder import track_upload, album_upload 
import yt_dlp

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album)/.+?/(.+)")

def ensure_download_dir(user, subdir=None):
    uid = user.get('user_id', 'temp_user')
    base = os.path.join("downloads", str(uid))
    if subdir:
        base = os.path.join(base, sanitize_filename(subdir))
    if not os.path.exists(base):
        os.makedirs(base)
    return base

async def start_jiosaavn(link: str, user: dict):
    msg = user['bot_msg']
    session = jiosaavn_manager.session
    api = jiosaavn_manager.api

    match = URL_REGEX.search(link)
    if not match: return

    kind, token_id = match.groups()
    
    if kind == 'song':
        await process_single_track(token_id, user, session, api)
    elif kind == 'album':
        await process_album(token_id, user, session, api)

async def process_single_track(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil info lagu...")
    try:
        track_data = await api.get_song_details(session, token_id)
        if not track_data: raise Exception("Metadata tidak ditemukan.")
        file_path, cover_path = await download_track_file(track_data, user, session, api)
        metadata = {
            'filepath': file_path, 'title': track_data.get("song"),
            'artist': track_data.get("primary_artists"), 'album': track_data.get("album"),
            'cover': cover_path, 'provider': 'JioSaavn', 'type': 'track'
        }
        await track_upload(metadata, user)
        await edit_message(msg, "Selesai!")
    except Exception as e:
        await edit_message(msg, f"Error: {e}")

async def process_album(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil data Album...")
    try:
        album_data = await api.get_album_details(session, token_id)
        tracks = album_data.get("list") or album_data.get("songs") or []
        if not tracks: raise Exception("Album kosong.")
        
        album_title = album_data.get("title", "Unknown Album")
        album_dir = ensure_download_dir(user, subdir=album_title)
        
        total = len(tracks)
        downloaded_tracks = []
        
        await edit_message(msg, f"Album: {album_title} ({total} tracks)")
        
        for i, track in enumerate(tracks):
            try:
                t_token = track['perma_url'].split('/')[-1] if 'perma_url' in track else None
                if not t_token: continue
                full_track = await api.get_song_details(session, t_token)
                if not full_track: full_track = track
                
                await edit_message(msg, f"[{i+1}/{total}] {full_track.get('song')}...")
                path, cover = await download_track_file(full_track, user, session, api, custom_dir=album_dir)
                downloaded_tracks.append({
                    'filepath': path, 'title': full_track.get("song"),
                    'artist': full_track.get("primary_artists"), 'album': full_track.get("album"),
                    'cover': cover
                })
            except Exception as e:
                LOGGER.error(f"Skip track {i}: {e}")

        if not downloaded_tracks:
            raise Exception("Gagal mengunduh semua lagu dalam album.")

        await edit_message(msg, "Memproses Album...")
        zip_path = None
        should_zip = user.get('zip', False) or user.get('zip_mode', False)
        
        if should_zip:
             await edit_message(msg, "Membuat ZIP...")
             zip_base = os.path.join(ensure_download_dir(user), sanitize_filename(album_title))
             zip_path = shutil.make_archive(zip_base, 'zip', album_dir)

        metadata = {
            'type': 'album', 'title': album_title,
            'artist': album_data.get("primary_artists"), 'folderpath': album_dir,
            'tracks': downloaded_tracks, 'cover': downloaded_tracks[0]['cover'] if downloaded_tracks else None,
            'zip_path': zip_path, 'poster_msg': user.get('poster', False) or user.get('art_poster', False),
            'provider': 'JioSaavn'
        }
        await album_upload(metadata, user)
        
    except Exception as e:
        # PENTING: Raise error agar download.py tahu tugas gagal
        LOGGER.error(f"JioSaavn Album Error: {e}")
        raise e

async def download_track_file(track_data, user, session, api, custom_dir=None):
    title = track_data.get("song")
    enc_url = track_data.get("encrypted_media_url")
    image_url = track_data.get("image", "").replace("150x150", "500x500")
    
    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    filename = f"{sanitize_filename(title)}.m4a"
    file_path = os.path.join(dl_dir, filename)

    # 1. Coba Generate Link 320kbps
    dl_url = await api.get_auth_url(session, enc_url)
    
    # List URL Percobaan (Priority: 320 -> 160 -> yt-dlp)
    urls_to_try = []
    if dl_url:
        urls_to_try.append(dl_url) # 320kbps (web->aac replaced)
        urls_to_try.append(dl_url.replace("_320.mp4", "_160.mp4")) # Fallback 160kbps
    
    downloaded = False
    
    # Metode 1: Manual Download (Cepat & Sesuai Bitrate)
    for url in urls_to_try:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 10000: # Validasi ukuran
                        async with aiofiles.open(file_path, mode='wb') as f:
                            await f.write(data)
                        downloaded = True
                        break
        except: pass
    
    # Metode 2: Fallback YT-DLP (Jika link manual mati 404)
    if not downloaded:
        LOGGER.info(f"Fallback ke yt-dlp untuk: {title}")
        if os.path.exists(file_path): os.remove(file_path)
        try:
            target = track_data.get('perma_url')
            if target:
                def run_ytdlp():
                    ydl_opts = {'format': 'bestaudio/best', 'outtmpl': file_path, 'quiet': True}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([target])
                await asyncio.to_thread(run_ytdlp)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                    downloaded = True
        except: pass

    if not downloaded: raise Exception("HTTP Error Download (Semua link gagal)")

    # Cover & Tags
    cover_path = os.path.join(dl_dir, "cover.jpg")
    if not os.path.exists(cover_path) and image_url:
        async with session.get(image_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                    await f.write(await resp.read())
    
    lyrics = None
    if track_data.get("has_lyrics") == "true":
        lyrics = await api.get_lyrics(session, track_data.get("id"))

    await set_jiosaavn_metadata(file_path, track_data, cover_path, lyrics)
    return file_path, cover_path
