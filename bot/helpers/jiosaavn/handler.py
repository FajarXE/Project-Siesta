import os
import re
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata

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
        # --- LOGIKA DOWNLOAD ALBUM ---
        await edit_message(msg, "Mengambil data Album...")
        album_data = await api.get_album_details(session, token_id)
        
        if not album_data or 'list' not in album_data:
            await edit_message(msg, "Gagal mengambil data album atau album kosong.")
            return

        tracks = album_data['list'] # List lagu ada di key 'list'
        total = len(tracks)
        await edit_message(msg, f"Ditemukan {total} lagu dalam album. Memulai download...")
        
        for i, track in enumerate(tracks):
            # Ambil Token ID dari perma_url
            # Format: .../song/judul/TOKEN
            perma_url = track.get('perma_url')
            song_token = perma_url.split('/')[-1]
            
            await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('song')}...")
            try:
                # Kita gunakan token lagu individual untuk diproses
                await process_track(song_token, user, session, api, is_album=True)
            except Exception as e:
                LOGGER.error(f"Gagal download track {i+1}: {e}")
                
        await edit_message(msg, "Download Album Selesai!")
        # -----------------------------

async def process_track(token_id, user, session, api, is_album=False):
    msg = user['bot_msg']
    if not is_album:
        await edit_message(msg, "Mengambil info lagu...")

    try:
        # 1. Metadata
        track_data = await api.get_song_details(session, token_id)
        if not track_data:
             raise Exception("Metadata lagu tidak ditemukan.")

        title = track_data.get("song")
        enc_url = track_data.get("encrypted_media_url")
        image_url = track_data.get("image", "").replace("150x150", "500x500")

        if not enc_url:
            raise Exception("URL media terenkripsi tidak ditemukan.")

        # 2. Link Download
        dl_url = await api.get_auth_url(session, enc_url)
        if not dl_url:
            raise Exception("Gagal generate link download.")

        # 3. Download File
        filename = f"{sanitize_filename(title)}.m4a"
        file_path = os.path.join(user['dir'], filename)
        
        async with session.get(dl_url) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP Error: {resp.status}")
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())

        # 4. Download Cover
        cover_path = None
        if image_url:
            cover_path = os.path.join(user['dir'], "cover.jpg")
            # Cek jika cover sudah ada (untuk album agar hemat bandwidth)
            if not os.path.exists(cover_path):
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        # 5. Metadata
        if not is_album:
             await edit_message(msg, "Menulis metadata...")
        await set_jiosaavn_metadata(file_path, track_data, cover_path)

        # 6. Upload
        if not is_album:
             await edit_message(msg, "Mengunggah...")
             
        chat_id = user.get('chat_id')
        client = user.get('client')
        if not client: from bot.tgclient import aio as client
        
        await client.send_audio(
            chat_id=chat_id,
            audio=file_path,
            thumb=cover_path,
            title=title,
            performer=track_data.get("primary_artists", "Unknown"),
            caption="Via JioSaavn DL"
        )
        
        # Hapus file setelah upload untuk menghemat ruang (terutama saat album)
        try:
            os.remove(file_path)
        except: pass

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"JioSaavn Error: {e}")
        if not is_album:
            raise e
