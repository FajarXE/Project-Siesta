import os
import re
import shutil
import asyncio
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata
from bot.helpers.uploder import track_upload, album_upload, playlist_upload 
from bot import Config
from bot.helpers.utils import fetch_zip_settings 
import yt_dlp

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album|featured|playlist)/.+?/(.+)")

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
    elif kind in ['featured', 'playlist']:
        await process_playlist(token_id, user, session, api)

async def process_single_track(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil info lagu...")
    try:
        track_data = await api.get_song_details(session, token_id)
        if not track_data: raise Exception("Metadata tidak ditemukan.")
        
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
        
        title = album_data.get("title", "Unknown Album")
        dl_dir = ensure_download_dir(user, subdir=title)
        
        total = len(tracks)
        downloaded_tracks = []
        is_explicit = "False"
        
        await edit_message(msg, f"Album: {title} ({total} tracks)")
        
        for i, track in enumerate(tracks):
            try:
                t_token = track['perma_url'].split('/')[-1] if 'perma_url' in track else None
                if not t_token: continue
                full_track = await api.get_song_details(session, t_token)
                if not full_track: full_track = track
                
                full_track['track_number'] = i + 1
                full_track['total_tracks'] = total
                if str(full_track.get("explicit_content")) == "1": is_explicit = "True"

                await edit_message(msg, f"[{i+1}/{total}] {full_track.get('song')}...")
                path, cover, dur = await download_track_file(full_track, user, session, api, custom_dir=dl_dir)
                
                downloaded_tracks.append({
                    'filepath': path, 'title': full_track.get("song"),
                    'artist': full_track.get("primary_artists"), 'album': full_track.get("album"),
                    'cover': cover, 'duration': dur, 'quality': '320kbps'
                })
            except Exception as e:
                LOGGER.error(f"Skip track {i}: {e}")

        if not downloaded_tracks: raise Exception("Gagal mengunduh semua lagu.")

        await edit_message(msg, "Memproses Album...")
        _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
        
        zip_path = None
        
        # Referensi Cover Utama (misal dari track pertama)
        final_cover_path = None
        if downloaded_tracks and downloaded_tracks[0].get('cover'):
            final_cover_path = downloaded_tracks[0]['cover']

        if is_album_zip:
             await edit_message(msg, "Membersihkan & Membuat ZIP...")
             
             # --- LOGIKA CLEANUP ALBUM ---
             # 1. Simpan satu cover sebagai 'cover.jpg'
             if final_cover_path and os.path.exists(final_cover_path):
                 clean_cover = os.path.join(dl_dir, "cover.jpg")
                 try:
                    shutil.copy(final_cover_path, clean_cover)
                    final_cover_path = clean_cover
                 except: pass
             
             # 2. Hapus semua file gambar lain
             for f in os.listdir(dl_dir):
                 if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                     if f != "cover.jpg":
                         try: os.remove(os.path.join(dl_dir, f))
                         except: pass
             # ----------------------------

             parent_dir = os.path.dirname(dl_dir)
             zip_name = sanitize_filename(title)
             base_name = os.path.join(parent_dir, zip_name)
             zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

        release_date = album_data.get("release_date") or album_data.get("year", "Unknown")

        if is_art_poster and final_cover_path and os.path.exists(final_cover_path):
            try:
                caption = (
                    f"**ᴛɪᴛʟᴇ :** {title}\n**ᴀʀᴛɪsᴛ :** {album_data.get('primary_artists')}\n"
                    f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                    f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                    f"**ᴘʀᴏᴠɪᴅᴇʀ :** JioSaavn\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
                )
                await send_message(user, final_cover_path, 'pic', caption=caption)
            except Exception as e: LOGGER.error(f"Gagal poster: {e}")

        metadata = {
            'type': 'album', 'title': title, 'artist': album_data.get("primary_artists"), 
            'folderpath': dl_dir, 'tracks': downloaded_tracks, 
            'cover': final_cover_path,
            'zip_path': zip_path, 'poster_msg': False, 'provider': 'JioSaavn', 
            'release_date': release_date, 'track_count': total, 'quality': '320kbps'
        }
        await album_upload(metadata, user)
        
    except Exception as e:
        LOGGER.error(f"JioSaavn Album Error: {e}")
        raise e

async def process_playlist(token_id, user, session, api, is_album=False):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil data Playlist...")
    try:
        pl_data = await api.get_playlist_details(session, token_id)
        tracks = pl_data.get("list") or pl_data.get("songs") or []
        if not tracks: raise Exception("Playlist kosong.")
        
        title = pl_data.get("listname") or pl_data.get("title") or "Unknown Playlist"
        
        dl_dir = ensure_download_dir(user, subdir=title)
        
        playlist_img = pl_data.get("image", "")
        playlist_cover_path = None
        if playlist_img:
            img_url = playlist_img.replace("150x150", "500x500").replace("50x50", "500x500")
            playlist_cover_path = os.path.join(dl_dir, "playlist_cover.jpg")
            try:
                async with session.get(img_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(playlist_cover_path, mode='wb') as f:
                            await f.write(await resp.read())
            except: 
                playlist_cover_path = None
        
        total = len(tracks)
        downloaded_tracks = []
        is_explicit = "False"
        
        await edit_message(msg, f"Playlist: {title} ({total} tracks)")
        
        for i, track in enumerate(tracks):
            try:
                t_token = track['perma_url'].split('/')[-1] if 'perma_url' in track else None
                if not t_token: continue
                full_track = await api.get_song_details(session, t_token)
                if not full_track: full_track = track
                
                full_track['track_number'] = i + 1
                full_track['total_tracks'] = total
                if str(full_track.get("explicit_content")) == "1": is_explicit = "True"

                await edit_message(msg, f"[{i+1}/{total}] {full_track.get('song')}...")
                path, cover, dur = await download_track_file(full_track, user, session, api, custom_dir=dl_dir)
                
                downloaded_tracks.append({
                    'filepath': path, 'title': full_track.get("song"),
                    'artist': full_track.get("primary_artists"), 'album': full_track.get("album"),
                    'cover': cover, 'duration': dur, 'quality': '320kbps'
                })
            except Exception as e:
                LOGGER.error(f"Skip track {i}: {e}")

        if not downloaded_tracks: raise Exception("Gagal mengunduh playlist.")

        await edit_message(msg, "Memproses Playlist...")
        is_pl_zip, _, _, is_art_poster = fetch_zip_settings(user)
        
        zip_path = None
        if is_pl_zip:
             await edit_message(msg, "Membersihkan & Membuat ZIP...")
             
             # Hapus cover individual, sisakan playlist_cover.jpg
             for f in os.listdir(dl_dir):
                 if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                     if f != "playlist_cover.jpg":
                         try: os.remove(os.path.join(dl_dir, f))
                         except: pass

             parent_dir = os.path.dirname(dl_dir)
             zip_name = sanitize_filename(title)
             base_name = os.path.join(parent_dir, zip_name)
             zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

        poster_img = playlist_cover_path if (playlist_cover_path and os.path.exists(playlist_cover_path)) else (downloaded_tracks[0]['cover'] if downloaded_tracks else None)

        if is_art_poster and poster_img:
            try:
                caption = (
                    f"**ᴛɪᴛʟᴇ :** {title}\n"
                    f"**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                    f"**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                    f"**ᴘʀᴏᴠɪᴅᴇʀ :** JioSaavn"
                )
                await send_message(user, poster_img, 'pic', caption=caption)
            except: pass

        metadata = {
            'type': 'playlist', 'title': title, 'folderpath': dl_dir, 
            'tracks': downloaded_tracks, 
            'cover': poster_img, 
            'zip_path': zip_path, 'poster_msg': False, 'provider': 'JioSaavn', 
            'track_count': total, 'quality': '320kbps'
        }
        await playlist_upload(metadata, user)
        
    except Exception as e:
        LOGGER.error(f"JioSaavn Playlist Error: {e}")
        raise e

async def download_track_file(track_data, user, session, api, custom_dir=None):
    title = track_data.get("song")
    enc_url = track_data.get("encrypted_media_url")
    base_img = track_data.get("image", "")
    
    img_1200 = base_img.replace("150x150", "1200x1200").replace("50x50", "1200x1200")
    img_500 = base_img.replace("150x150", "500x500").replace("50x50", "500x500")
    
    track_num = track_data.get('track_number')
    safe_title = sanitize_filename(title)
    if track_num: filename = f"{int(track_num)} - {safe_title}.m4a"
    else: filename = f"{safe_title}.m4a"

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

    cover_filename = f"{safe_title}.jpg"
    cover_path = os.path.join(dl_dir, cover_filename)
    cover_downloaded = False
    
    if not os.path.exists(cover_path) and base_img:
        try:
            async with session.get(img_1200) as resp:
                if resp.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await resp.read())
                    cover_downloaded = True
        except: pass
        
        if not cover_downloaded:
            try:
                async with session.get(img_500) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())
            except: pass
    
    lyrics = None
    if track_data.get("has_lyrics") == "true":
        lyrics = await api.get_lyrics(session, track_data.get("id"))

    duration = await set_jiosaavn_metadata(file_path, track_data, cover_path, lyrics)
    return file_path, cover_path, duration
