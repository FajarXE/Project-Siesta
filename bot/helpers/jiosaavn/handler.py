import os
import re
import shutil
import asyncio
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata
from bot.helpers.uploder import track_upload, album_upload 
from bot import Config
from bot.helpers.utils import fetch_zip_settings 
import yt_dlp

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album)/.+?/(.+)")

def ensure_download_dir(user, subdir=None):
    base_dir = Config.DOWNLOAD_BASE_DIR
    uid = user.get('user_id', 'temp')
    user_dir = os.path.join(base_dir, str(uid))
    if subdir:
        user_dir = os.path.join(user_dir, sanitize_filename(subdir))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

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
        
        # Inject info track 1/1 untuk single
        track_data['track_number'] = 1
        track_data['total_tracks'] = 1
        
        file_path, cover_path, duration = await download_track_file(track_data, user, session, api)
        
        metadata = {
            'filepath': file_path, 'title': track_data.get("song"),
            'artist': track_data.get("primary_artists"), 'album': track_data.get("album"),
            'cover': cover_path, 'provider': 'JioSaavn', 'type': 'track',
            'duration': duration, 'quality': '320kbps'
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
        is_explicit_album = "False"
        
        await edit_message(msg, f"Album: {album_title} ({total} tracks)")
        
        for i, track in enumerate(tracks):
            try:
                t_token = track['perma_url'].split('/')[-1] if 'perma_url' in track else None
                if not t_token: continue
                full_track = await api.get_song_details(session, t_token)
                if not full_track: full_track = track
                
                # INJECT METADATA TRACK NUMBER
                current_num = i + 1
                full_track['track_number'] = current_num
                full_track['total_tracks'] = total
                
                if str(full_track.get("explicit_content")) == "1":
                    is_explicit_album = "True"

                await edit_message(msg, f"[{current_num}/{total}] {full_track.get('song')}...")
                path, cover, dur = await download_track_file(full_track, user, session, api, custom_dir=album_dir)
                
                downloaded_tracks.append({
                    'filepath': path, 'title': full_track.get("song"),
                    'artist': full_track.get("primary_artists"), 'album': full_track.get("album"),
                    'cover': cover, 'duration': dur, 'quality': '320kbps'
                })
            except Exception as e:
                LOGGER.error(f"Skip track {i}: {e}")

        if not downloaded_tracks:
            raise Exception("Gagal mengunduh semua lagu.")

        await edit_message(msg, "Memproses Album...")
        
        _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
        
        zip_path = None
        if is_album_zip:
             await edit_message(msg, "Mengompres (ZIP)...")
             parent_dir = os.path.dirname(album_dir)
             zip_name = sanitize_filename(album_title)
             base_name = os.path.join(parent_dir, zip_name)
             zip_path = shutil.make_archive(base_name, 'zip', album_dir)

        if is_art_poster and downloaded_tracks:
            cover_file = downloaded_tracks[0]['cover']
            if cover_file and os.path.exists(cover_file):
                try:
                    caption = (
                        f"**ᴛɪᴛʟᴇ :** {album_title}\n"
                        f"**ᴀʀᴛɪsᴛ :** {album_data.get('primary_artists')}\n"
                        f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {album_data.get('year')}\n"
                        f"**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                        f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n"
                        f"**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                        f"**ᴘʀᴏᴠɪᴅᴇʀ :** JioSaavn\n"
                        f"**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit_album}"
                    )
                    await send_message(user, cover_file, 'pic', caption=caption)
                except Exception as e:
                    LOGGER.error(f"Gagal kirim Poster JioSaavn: {e}")

        metadata = {
            'type': 'album', 'title': album_title,
            'artist': album_data.get("primary_artists"), 'folderpath': album_dir,
            'tracks': downloaded_tracks, 
            'cover': downloaded_tracks[0]['cover'] if downloaded_tracks else None,
            'zip_path': zip_path, 'poster_msg': False, 
            'provider': 'JioSaavn', 'release_date': album_data.get("year", ""), 
            'track_count': total, 'quality': '320kbps'
        }

        await album_upload(metadata, user)
        
    except Exception as e:
        LOGGER.error(f"JioSaavn Album Error: {e}")
        raise e

async def download_track_file(track_data, user, session, api, custom_dir=None):
    title = track_data.get("song")
    enc_url = track_data.get("encrypted_media_url")
    image_url = track_data.get("image", "").replace("150x150", "500x500")
    
    # --- NOMOR PADA NAMA FILE (Format: 1 - Judul) ---
    track_num = track_data.get('track_number')
    safe_title = sanitize_filename(title)
    
    if track_num:
        # int() akan mengubah 01 menjadi 1
        filename = f"{int(track_num)} - {safe_title}.m4a"
    else:
        filename = f"{safe_title}.m4a"
    # -----------------------------------------------

    dl_dir = custom_dir if custom_dir else ensure_download_dir(user)
    file_path = os.path.join(dl_dir, filename)

    dl_url = await api.get_auth_url(session, enc_url)
    urls_to_try = []
    if dl_url:
        urls_to_try.append(dl_url) 
        urls_to_try.append(dl_url.replace("_320.mp4", "_160.mp4"))
    
    downloaded = False
    for url in urls_to_try:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if len(data) > 10000:
                        async with aiofiles.open(file_path, mode='wb') as f:
                            await f.write(data)
                        downloaded = True
                        break
        except: pass
    
    if not downloaded:
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

    if not downloaded: raise Exception("HTTP Error Download")

    cover_path = os.path.join(dl_dir, "cover.jpg")
    if not os.path.exists(cover_path) and image_url:
        async with session.get(image_url) as resp:
            if resp.status == 200:
                async with aiofiles.open(cover_path, mode='wb') as f:
                    await f.write(await resp.read())
    
    lyrics = None
    if track_data.get("has_lyrics") == "true":
        lyrics = await api.get_lyrics(session, track_data.get("id"))

    duration = await set_jiosaavn_metadata(file_path, track_data, cover_path, lyrics)
    return file_path, cover_path, duration
