import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.utils import sanitize_filename
from bot.helpers.message import edit_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata

# Regex untuk menangkap Token ID dari URL
# Contoh: https://www.jiosaavn.com/song/track-name/Iz0xcB1,RFw_
URL_REGEX = re.compile(r"jiosaavn\.com/(song|album)/.+?/(.+)")

async def start_jiosaavn(link: str, user: dict):
    msg = user['bot_msg']
    session = jiosaavn_manager.session
    api = jiosaavn_manager.api

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link JioSaavn tidak valid atau tidak didukung.")
        return

    kind, token_id = match.groups()
    
    if kind == 'song':
        await process_track(token_id, user, session, api)
    elif kind == 'album':
        await edit_message(msg, "Download Album JioSaavn belum diimplementasikan (Hanya Single).")
    
async def process_track(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "Mengambil info lagu JioSaavn...")

    try:
        # 1. Get Metadata
        track_data = await api.get_song_details(session, token_id)
        if not track_data:
             raise Exception("Metadata lagu tidak ditemukan.")

        title = track_data.get("song")
        enc_url = track_data.get("encrypted_media_url")
        image_url = track_data.get("image", "").replace("150x150", "500x500")

        if not enc_url:
            raise Exception("URL media terenkripsi tidak ditemukan.")

        # 2. Get Stream URL
        dl_url = await api.get_auth_url(session, enc_url)
        if not dl_url:
            raise Exception("Gagal membuat link download (Region blocked?).")

        # 3. Download Audio
        filename = f"{sanitize_filename(title)}.m4a"
        file_path = os.path.join(user['dir'], filename)
        
        await edit_message(msg, f"Mengunduh: {title}...")
        
        async with session.get(dl_url) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal download file audio: {resp.status}")
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())

        # 4. Download Cover
        cover_path = None
        if image_url:
            cover_path = os.path.join(user['dir'], "cover.jpg")
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await resp.read())

        # 5. Metadata Tagging
        await edit_message(msg, "Menulis metadata...")
        await set_jiosaavn_metadata(file_path, track_data, cover_path)

        # 6. Upload
        await edit_message(msg, "Mengunggah...")
        from bot.helpers.uploader import upload_file # Asumsi ada helper uploader
        await upload_file(file_path, user, cover_path)

    except Exception as e:
        LOGGER.error(f"JioSaavn Error: {e}")
        raise e
