import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata

# --- FUNGSI SANITIZE LOKAL (PENGGANTI IMPORT UTILS) ---
def sanitize_filename(name: str) -> str:
    # Hapus karakter ilegal untuk nama file Windows/Linux
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()
# ------------------------------------------------------

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
        await process_gaana_track(identifier, user, session, api)
    else:
        await edit_message(msg, f"Tipe '{content_type}' belum didukung, hanya 'song'.")

async def process_gaana_track(identifier, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil info lagu Gaana...")

    try:
        # 1. Metadata
        data = await api.get_metadata(session, identifier, 'songDetail')
        if not data or 'tracks' not in data or not data['tracks']:
            raise Exception("Lagu tidak ditemukan di Gaana.")
        
        track_info = data['tracks'][0]
        title = track_info.get("track_title", "Unknown")
        
        # 2. Decrypt URL
        enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
        if not enc_path:
             raise Exception("Stream path tidak ditemukan.")
             
        decrypted_url = api.decrypt_stream_path(enc_path)
        
        # Ubah kualitas menjadi high
        final_url = decrypted_url.replace("medium.mp4", "high.mp4").replace("low.mp4", "high.mp4")

        # 3. Download
        filename = f"{sanitize_filename(title)}.mp4"
        file_path = os.path.join(user['dir'], filename)
        
        await edit_message(msg, f"Mengunduh: {title}...")
        
        async with session.get(final_url) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal download stream: {resp.status}")
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())
                
        # 4. Cover Art
        artwork_url = track_info.get('artwork')
        cover_path = None
        if artwork_url:
            artwork_url = artwork_url.replace('size_s', 'size_l') 
            cover_path = os.path.join(user['dir'], "cover.jpg")
            async with session.get(artwork_url) as resp:
                 if resp.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await resp.read())

        # 5. Metadata
        await edit_message(msg, "Menulis metadata...")
        await set_gaana_metadata(file_path, track_info, cover_path)
        
        # 6. Upload Manual (Aman dari error import uploader)
        await edit_message(msg, "Mengunggah...")
        chat_id = user.get('chat_id')
        client = user.get('client')
        if not client:
             from bot.tgclient import aio as client
             
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
        await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"Gaana Error: {e}")
        # Re-raise agar ditangkap download.py
        raise e
