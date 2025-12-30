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

# --- FUNGSI HELPER BARU ---
def ensure_download_dir(user):
    if 'dir' not in user or not user['dir']:
        uid = user.get('user_id', 'temp_user')
        user['dir'] = os.path.join("downloads", str(uid))
    if not os.path.exists(user['dir']):
        os.makedirs(user['dir'])
    return user['dir']
# --------------------------

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
        
        # --- FIX: Cek berbagai kemungkinan key ---
        tracks = []
        if album_data:
            if 'list' in album_data:
                tracks = album_data['list']
            elif 'songs' in album_data:
                tracks = album_data['songs']
        
        if not tracks:
            LOGGER.error(f"DEBUG Jiosaavn Album Data: {album_data.keys() if album_data else 'None'}")
            await edit_message(msg, "Gagal mengambil data album (struktur JSON tidak dikenali).")
            return

        total = len(tracks)
        await edit_message(msg, f"Ditemukan {total} lagu dalam album. Memulai download...")
        
        for i, track in enumerate(tracks):
            # Coba ambil token. Kadang object track sudah lengkap, kadang cuma summary.
            # Jika perma_url ada, ambil token dari URL.
            try:
                if 'perma_url' in track:
                    song_token = track['perma_url'].split('/')[-1]
                elif 'id' in track:
                    # Kadang ID di list album sudah terenkripsi, kadang tidak.
                    # Kita coba pakai 'id' kalau perma_url tidak ada
                    # Tapi API get_song_details butuh Token (pids), bukan ID numeric.
                    # Kita coba cari 'encrypted_media_url' langsung di list ini
                    if 'encrypted_media_url' in track:
                        # Langsung proses tanpa fetch detail lagi
                        await process_track_direct(track, user, session, api, is_album=True)
                        continue
                    else:
                        LOGGER.warning(f"Track {i+1} tidak memiliki perma_url/media_url. Skip.")
                        continue
                else:
                    continue

                await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track.get('song', 'Unknown')}...")
                await process_track(song_token, user, session, api, is_album=True)
            except Exception as e:
                LOGGER.error(f"Gagal download track {i+1}: {e}")
                
        await edit_message(msg, "Download Album Selesai!")

# Helper baru untuk memproses track jika data sudah lengkap di list album
async def process_track_direct(track_data, user, session, api, is_album=True):
    # Logika sama dengan process_track tapi skip fetch metadata
    try:
        title = track_data.get("song")
        enc_url = track_data.get("encrypted_media_url")
        image_url = track_data.get("image", "").replace("150x150", "500x500")

        if not enc_url: return

        dl_url = await api.get_auth_url(session, enc_url)
        if not dl_url: return

        filename = f"{sanitize_filename(title)}.m4a"
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        async with session.get(dl_url) as resp:
            if resp.status != 200: return
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(await resp.read())

        cover_path = None
        if image_url:
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        await set_jiosaavn_metadata(file_path, track_data, cover_path)

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
    except Exception as e:
        LOGGER.error(f"Direct Track Error: {e}")

async def process_track(token_id, user, session, api, is_album=False):
    msg = user['bot_msg']
    if not is_album:
        await edit_message(msg, "Mengambil info lagu...")

    try:
        track_data = await api.get_song_details(session, token_id)
        if not track_data:
             raise Exception("Metadata lagu tidak ditemukan.")

        # Panggil helper direct agar tidak duplikasi kode
        await process_track_direct(track_data, user, session, api, is_album)
        
        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"JioSaavn Error: {e}")
        if not is_album:
            raise e
