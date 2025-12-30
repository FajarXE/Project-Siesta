import os
import re
import aiohttp
import aiofiles
from urllib.parse import urljoin
from bot.logger import LOGGER
from bot.helpers.message import edit_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

def ensure_download_dir(user):
    if 'dir' not in user or not user['dir']:
        uid = user.get('user_id', 'temp_user')
        user['dir'] = os.path.join("downloads", str(uid))
    if not os.path.exists(user['dir']):
        os.makedirs(user['dir'])
    return user['dir']

async def start_gaana(link: str, user: dict):
    msg = user['bot_msg']
    session = gaana_manager.session
    api = gaana_manager.api

    ensure_download_dir(user)

    match = URL_REGEX.search(link)
    if not match:
        await edit_message(msg, "Link Gaana tidak valid.")
        return

    content_type, identifier = match.groups()

    if content_type == 'song':
        data = await api.get_metadata(session, identifier, 'songDetail')
        if data and 'tracks' in data and data['tracks']:
            await process_gaana_track(data['tracks'][0], user, session, api)
        else:
            await edit_message(msg, "Lagu tidak ditemukan.")

    elif content_type == 'album':
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
        # Default replace
        final_url = decrypted_url.replace("medium.mp4", "high.mp4").replace("low.mp4", "high.mp4")

        # 2. Download (Support M3U8 & MP4)
        filename = f"{sanitize_filename(title)}.mp4"
        dl_dir = ensure_download_dir(user)
        file_path = os.path.join(dl_dir, filename)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
            'Referer': 'https://gaana.com/'
        }
        
        # Download konten pertama (bisa mp4 atau m3u8)
        content_bytes = b""
        async with session.get(final_url, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal download stream: {resp.status}")
            content_bytes = await resp.read()

        # Cek apakah konten adalah M3U8 Playlist
        content_str = ""
        try:
            content_str = content_bytes.decode('utf-8', errors='ignore')
        except: pass

        if "#EXTM3U" in content_str:
            # --- PARSING M3U8 ---
            LOGGER.info(f"Gaana: M3U8 Terdeteksi untuk {title}. Mencari kualitas terbaik...")
            best_url = parse_m3u8_best_quality(content_str, final_url)
            
            if not best_url:
                raise Exception("Gagal mengekstrak URL dari playlist M3U8.")
            
            # Download ulang menggunakan URL dari dalam M3U8
            async with session.get(best_url, headers=headers) as resp2:
                if resp2.status != 200:
                    raise Exception(f"Gagal download segmen audio: {resp2.status}")
                async with aiofiles.open(file_path, mode='wb') as f:
                    await f.write(await resp2.read())
        else:
            # Jika bukan m3u8, simpan bytes yang sudah didownload
            async with aiofiles.open(file_path, mode='wb') as f:
                await f.write(content_bytes)

        # Cek validitas file
        if os.path.getsize(file_path) < 2000:
             os.remove(file_path)
             raise Exception("File terlalu kecil (Error/Geoblock).")

        # 3. Cover Art & Metadata
        artwork_url = track_info.get('artwork')
        cover_path = None
        if artwork_url:
            artwork_url = artwork_url.replace('size_s', 'size_l') 
            cover_path = os.path.join(dl_dir, "cover.jpg")
            if not os.path.exists(cover_path):
                async with session.get(artwork_url) as resp:
                     if resp.status == 200:
                        async with aiofiles.open(cover_path, mode='wb') as f:
                            await f.write(await resp.read())

        try:
            await set_gaana_metadata(file_path, track_info, cover_path)
        except Exception as e:
            LOGGER.warning(f"Metadata skip: {e}")
        
        # 4. Upload
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
        
        try: os.remove(file_path)
        except: pass

        if not is_album:
            await edit_message(msg, "Selesai!")

    except Exception as e:
        LOGGER.error(f"Gaana Error: {e}")
        if not is_album: raise e

def parse_m3u8_best_quality(m3u8_content, base_url):
    """
    Mencari URL dengan bandwidth tertinggi dari konten m3u8 text.
    Mengembalikan URL absolut.
    """
    lines = m3u8_content.split('\n')
    max_bandwidth = -1
    best_uri = None
    
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF'):
            # Cari atribut BANDWIDTH
            match = re.search(r'BANDWIDTH=(\d+)', line)
            if match:
                bandwidth = int(match.group(1))
                if bandwidth > max_bandwidth:
                    # URL stream biasanya ada di baris berikutnya
                    if i + 1 < len(lines):
                        uri_line = lines[i+1].strip()
                        if uri_line and not uri_line.startswith('#'):
                            max_bandwidth = bandwidth
                            best_uri = uri_line
    
    if best_uri:
        # Jika URL relatif, gabungkan dengan base_url
        if not best_uri.startswith('http'):
            return urljoin(base_url, best_uri)
        return best_uri
    return None
