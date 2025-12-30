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

def ensure_download_dir(user):
    if 'dir' not in user or not user['dir']:
        uid = user.get('user_id', 'temp_user')
        user['dir'] = os.path.join("downloads", str(uid))
    if not os.path.exists(user['dir']):
        os.makedirs(user['dir'])
    return user['dir']

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
                # Cari Token ID
                song_token = None
                if 'perma_url' in track:
                    song_token = track['perma_url'].split('/')[-1]
                elif 'url' in track: # Kadang key-nya url
                    song_token = track['url'].split('/')[-1]
                
                if not song_token:
                    LOGGER.warning(f"Track {i+1} skip: Tidak ada token.")
                    continue

                await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('song', 'Unknown')}...")
                
                # Kita panggil process_track standar agar lebih stabil
                # (Fetch metadata fresh + Auth URL fresh)
                await process_track(song_token, user, session, api, is_album=True)
                
            except Exception as e:
                LOGGER.error(f"Gagal download track JioSaavn {i+1}: {e}")
                
        await edit_message(msg, "Download Album Selesai!")

async def process_track(token_id, user, session, api, is_album=False):
    msg = user['bot_msg']
    if not is_album:
        await edit_message(msg, "Mengambil info lagu...")

    try:
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

        # 3. Download File dengan Headers (FIX PENTING)
        filename = f"{sanitize_filename(title)}.m4a"
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        async with session.get(dl_url, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP Error: {resp.status}")
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())

        # Cek validitas file
        if os.path.getsize(file_path) < 1000:
             os.remove(file_path)
             raise Exception("File kosong/corrupt (Geoblock?).")

        # 4. Download Cover
        cover_path = None
        if image_url:
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        # 5. Metadata
        try:
             await set_jiosaavn_metadata(file_path, track_data, cover_path)
        except: pass

        # 6. Upload
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
        
        try: os.remove(file_path)
        except: pass

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"JioSaavn Error: {e}")
        if not is_album:
            raise e
