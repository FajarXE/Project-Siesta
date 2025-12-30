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
                song_token = None
                if 'perma_url' in track:
                    song_token = track['perma_url'].split('/')[-1]
                elif 'url' in track:
                    song_token = track['url'].split('/')[-1]
                
                if not song_token: continue

                await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('song', 'Unknown')}...")
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
        preview_url = track_data.get("media_preview_url") 
        image_url = track_data.get("image", "").replace("150x150", "500x500")

        # --- LOGIKA RETRY DOWNLOAD ---
        dl_url = await api.get_auth_url(session, enc_url, preview_url)
        
        # Siapkan opsi fallback manual jika link yang didapat juga 404
        # Ini terjadi jika generateAuthToken gagal, dan fallback di api.py mengembalikan link _320 yang ternyata mati
        fallback_urls = []
        if preview_url:
            # Link 320kbps
            fallback_urls.append(preview_url.replace("preview.saavncdn.com", "aac.saavncdn.com").replace("_96_p.mp4", "_320.mp4"))
            # Link 160kbps (Cadangan jika 320 mati)
            fallback_urls.append(preview_url.replace("preview.saavncdn.com", "aac.saavncdn.com").replace("_96_p.mp4", "_160.mp4"))
        
        # Tambahkan link utama ke antrian
        download_queue = []
        if dl_url: download_queue.append(dl_url)
        download_queue.extend(fallback_urls)

        # Hapus duplikat
        download_queue = list(dict.fromkeys(download_queue))

        if not download_queue:
            raise Exception("Gagal membuat link download.")

        filename = f"{sanitize_filename(title)}.m4a"
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        downloaded = False
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

        # Loop semua kemungkinan URL sampai berhasil
        for url in download_queue:
            try:
                LOGGER.info(f"Mencoba download dari: {url}")
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        if len(content) > 10000: # Cek jika bukan file error kecil
                            async with aiofiles.open(file_path, mode='wb') as f:
                                await f.write(content)
                            downloaded = True
                            break
                    else:
                        LOGGER.warning(f"Gagal {url} dengan status {resp.status}")
            except Exception as e:
                LOGGER.error(f"Error koneksi ke {url}: {e}")

        if not downloaded:
             raise Exception("Gagal download: Semua link mengembalikan 404/Error.")
        # -----------------------------

        # 4. Cover & Metadata
        cover_path = None
        if image_url:
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        try:
             await set_jiosaavn_metadata(file_path, track_data, cover_path)
        except: pass

        # 5. Upload
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
        if not is_album: raise e
