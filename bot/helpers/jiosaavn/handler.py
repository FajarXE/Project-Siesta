import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata

# Fungsi Sanitize Lokal
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album)/.+?/(.+)")

async def start_jiosaavn(link: str, user: dict):
    msg = user['bot_msg']
    session = jiosaavn_manager.session
    api = jiosaavn_manager.api

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link JioSaavn tidak valid.")
        return

    kind, token_id = match.groups()
    
    if kind == 'song':
        await process_track(token_id, user, session, api)
    elif kind == 'album':
        await edit_message(msg, "Album belum didukung.")
    
async def process_track(token_id, user, session, api):
    msg = user['bot_msg']
    LOGGER.info(f"DEBUG: Memulai proses track ID: {token_id}")
    await edit_message(msg, "Mengambil info lagu...")

    try:
        # 1. Metadata
        track_data = await api.get_song_details(session, token_id)
        if not track_data:
             LOGGER.error("DEBUG: Metadata kosong!")
             raise Exception("Metadata lagu tidak ditemukan.")
        
        LOGGER.info(f"DEBUG: Metadata didapat: {track_data.get('song')}")

        title = track_data.get("song")
        enc_url = track_data.get("encrypted_media_url")
        image_url = track_data.get("image", "").replace("150x150", "500x500")

        if not enc_url:
            raise Exception("URL media terenkripsi tidak ditemukan.")

        # 2. Auth URL
        dl_url = await api.get_auth_url(session, enc_url)
        if not dl_url:
            raise Exception("Gagal generate link download (Mungkin Region Block).")
            
        LOGGER.info(f"DEBUG: Link download didapat: {dl_url}")

        # 3. Download
        filename = f"{sanitize_filename(title)}.m4a"
        file_path = os.path.join(user['dir'], filename)
        
        await edit_message(msg, f"Mengunduh: {title}...")
        
        async with session.get(dl_url) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal download HTTP Status: {resp.status}")
            
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())
        
        # --- CEK UKURAN FILE (PENTING) ---
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            LOGGER.info(f"DEBUG: File berhasil disimpan. Ukuran: {file_size} bytes di {file_path}")
            if file_size < 1000: # Jika file kurang dari 1KB, pasti error
                raise Exception(f"File terunduh tapi kosong/corrupt (Hanya {file_size} bytes). Cek link/region.")
        else:
            raise Exception("File tidak ditemukan setelah download!")
        # ---------------------------------

        # 4. Cover
        cover_path = None
        if image_url:
            cover_path = os.path.join(user['dir'], "cover.jpg")
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await resp.read())

        # 5. Metadata
        await edit_message(msg, "Menulis metadata...")
        await set_jiosaavn_metadata(file_path, track_data, cover_path)

        # 6. Upload
        await edit_message(msg, "Mengunggah...")
        LOGGER.info("DEBUG: Memulai proses upload manual...")
        
        chat_id = user.get('chat_id')
        client = user.get('client')
        if not client:
             from bot.tgclient import aio as client
        
        await client.send_audio(
            chat_id=chat_id,
            audio=file_path,
            thumb=cover_path,
            title=title,
            performer=track_data.get("primary_artists", "Unknown"),
            caption="Via JioSaavn DL"
        )
        LOGGER.info("DEBUG: Upload selesai!")
        await edit_message(msg, "Selesai! (Cek pesan audio)")

    except Exception as e:
        LOGGER.error(f"JioSaavn Handled Error: {e}")
        import traceback
        LOGGER.error(traceback.format_exc()) # Print full error
        await edit_message(msg, f"Error: {e}")
        raise e
