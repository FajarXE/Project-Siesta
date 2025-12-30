import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.utils import sanitize_filename
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata

# Regex menangkap tipe dan ID
# Contoh: https://gaana.com/song/lagu-keren
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
        # Type untuk API Gaana: song -> songDetail
        data = await api.get_metadata(session, identifier, 'songDetail')
        if not data or 'tracks' not in data or not data['tracks']:
            raise Exception("Lagu tidak ditemukan di Gaana.")
        
        track_info = data['tracks'][0]
        title = track_info.get("track_title", "Unknown")
        
        # 2. Decrypt URL
        # path terenkripsi ada di urls -> auto -> message
        enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
        if not enc_path:
             raise Exception("Stream path tidak ditemukan.")
             
        decrypted_url = api.decrypt_stream_path(enc_path)
        
        # Ubah kualitas menjadi high/best (sesuai referensi gaana.py)
        # Asumsi 'medium.mp4' -> 'high.mp4' atau bitrate lain
        # Kita pakai default yang didekripsi, atau replace jika perlu:
        final_url = decrypted_url.replace("medium.mp4", "high.mp4").replace("low.mp4", "high.mp4")

        # 3. Download
        filename = f"{sanitize_filename(title)}.mp4" # Gaana stream biasanya mp4 audio container
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
            artwork_url = artwork_url.replace('size_s', 'size_l') # High Quality Cover
            cover_path = os.path.join(user['dir'], "cover.jpg")
            async with session.get(artwork_url) as resp:
                 if resp.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await resp.read())

        # 5. Metadata
        await edit_message(msg, "Menulis metadata...")
        await set_gaana_metadata(file_path, track_info, cover_path)
        
        # 6. Upload
        await edit_message(msg, "Mengunggah...")
        from bot.helpers.uploader import upload_file
        await upload_file(file_path, user, cover_path)

    except Exception as e:
        LOGGER.error(f"Gaana Error: {e}")
        raise e
