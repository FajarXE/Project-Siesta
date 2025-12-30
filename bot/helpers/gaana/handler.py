import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

async def start_gaana(link: str, user: dict):
    msg = user['bot_msg']
    session = gaana_manager.session
    api = gaana_manager.api

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link Gaana tidak valid.")
        return

    content_type, identifier = match.groups()

    if content_type == 'song':
        # Ambil metadata songDetail
        data = await api.get_metadata(session, identifier, 'songDetail')
        if data and 'tracks' in data and data['tracks']:
            await process_gaana_track(data['tracks'][0], user, session, api)
        else:
            await edit_message(msg, "Lagu tidak ditemukan.")

    elif content_type == 'album':
        # --- LOGIKA ALBUM GAANA ---
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
        # --------------------------
    
    elif content_type == 'playlist':
        await edit_message(msg, "Playlist belum didukung.")

async def process_gaana_track(track_info, user, session, api, is_album=False):
    msg = user['bot_msg']
    
    try:
        title = track_info.get("track_title", "Unknown")
        
        # 1. Decrypt URL
        enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
        if not enc_path:
             raise Exception("Stream path tidak ditemukan.")
             
        decrypted_url = api.decrypt_stream_path(enc_path)
        final_url = decrypted_url.replace("medium.mp4", "high.mp4").replace("low.mp4", "high.mp4")

        # 2. Download
        filename = f"{sanitize_filename(title)}.mp4"
        file_path = os.path.join(user['dir'], filename)
        
        async with session.get(final_url) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal download stream: {resp.status}")
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())
                
        # 3. Cover Art
        artwork_url = track_info.get('artwork')
        cover_path = None
        if artwork_url:
            artwork_url = artwork_url.replace('size_s', 'size_l') 
            cover_path = os.path.join(user['dir'], "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(artwork_url) as resp:
                     if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        # 4. Metadata
        await set_gaana_metadata(file_path, track_info, cover_path)
        
        # 5. Upload Manual
        chat_id = user.get('chat_id')
        client = user.get('client')
        if not client: from bot.tgclient import aio as client
             
        artists = track_info.get("artist", [])
        artist_name = artists[0]['name'] if artists else "Unknown"

        await client.send_audio(
            chat_id=chat_id,
            audio=file_path,
            thumb=cover_path,
            title=title,
            performer=artist_name,
            caption="Via Gaana DL"
        )
        
        # Hapus file setelah upload
        try:
            os.remove(file_path)
        except: pass

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"Gaana Error: {e}")
        if not is_album:
            raise e
