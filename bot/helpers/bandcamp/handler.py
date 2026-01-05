import os
import re
import shutil
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import bandcamp_manager
from .metadata import set_bandcamp_metadata
from bot.helpers.uploder import track_upload, album_upload
from bot import Config
from bot.helpers.utils import fetch_zip_settings

BANDCAMP_REGEX = re.compile(r'https?://[^/]+\.bandcamp\.com/(track|album)/[^/?#]+')

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def ensure_download_dir(user, subdir=None):
    base_dir = Config.DOWNLOAD_BASE_DIR
    uid = user.get('user_id', 'temp')
    user_dir = os.path.join(base_dir, str(uid))
    if subdir:
        user_dir = os.path.join(user_dir, sanitize_filename(subdir))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

async def start_bandcamp(link: str, user: dict):
    msg = user['bot_msg']
    session = bandcamp_manager.session
    api = bandcamp_manager.api

    if "bandcamp.com" not in link:
        await edit_message(msg, "Link Bandcamp tidak valid.")
        return

    await edit_message(msg, "Mengambil data dari Bandcamp...")
    
    data = await api.get_track_or_album(session, link)
    if not data:
        await edit_message(msg, "Gagal mengambil metadata (Mungkin Geo-blocked atau URL salah).")
        return

    artist = data['artist']
    album_title = data['album_title']
    tracks = data['tracks']
    is_album = data['is_album']
    release_date = data['release_date'] # Format YYYY-MM-DD
    genre = data['genre']
    label = data['label']
    is_explicit = data['explicit'] 
    
    json_raw = data.get('raw', {})
    
    # 1. Copyright
    # Biasanya format "YYYY Label"
    copyright_text = json_raw.get('copyright') or f"{release_date[:4]} {label or artist}"
    
    # 2. Credits / Composer
    credits = json_raw.get('credits', "")
    composer = artist
    if credits and len(credits) < 50:
        composer = credits.replace("Written by", "").strip()

    dl_dir = ensure_download_dir(user, subdir=album_title)
    
    cover_path = os.path.join(dl_dir, "cover.jpg")
    cover_url = f"https://f4.bcbits.com/img/a{data['art_id']}_10.jpg" if data['art_id'] else None
    
    if cover_url:
        try:
            async with session.get(cover_url) as r:
                if r.status == 200:
                    async with aiofiles.open(cover_path, mode='wb') as f:
                        await f.write(await r.read())
                else: cover_path = None
        except: cover_path = None

    downloaded_tracks = []
    total = len(tracks)

    await edit_message(msg, f"Ditemukan: {album_title} ({total} tracks)")

    for i, track in enumerate(tracks):
        file_info = track.get('file')
        if not file_info or 'mp3-128' not in file_info:
            LOGGER.warning(f"Track {track.get('title')} tidak memiliki stream gratis.")
            continue

        track_url = file_info['mp3-128']
        track_title = track.get('title', f"Track {i+1}")
        
        raw_track_num = track.get('track_num')
        track_num = i + 1 
        if raw_track_num is not None:
            try:
                track_num = int(raw_track_num)
            except ValueError:
                track_num = i + 1
        
        await edit_message(msg, f"[{i+1}/{total}] Mengunduh: {track_title}...")
        
        filename = f"{track_num:02d} - {sanitize_filename(track_title)}.mp3"
        file_path = os.path.join(dl_dir, filename)
        
        try:
            async with session.get(track_url) as r:
                if r.status == 200:
                    async with aiofiles.open(file_path, mode='wb') as f:
                        await f.write(await r.read())
                else: continue
        except: continue

        # Lyrics
        lyrics_text = track.get('lyrics') or None
        
        # --- UPDATE METADATA PAYLOAD ---
        # 1. Hapus 'comment' dan 'url' sesuai request
        # 2. Ganti 'year' menjadi 'date' (isi full YYYY-MM-DD)
        meta_payload = {
            'filepath': file_path,
            'title': track_title,
            'artist': artist,
            'album': album_title,
            'track_num': track_num,
            'total_tracks': total,
            'cover_path': cover_path,
            'date': release_date, # Masukkan Tanggal Lengkap
            'genre': genre,
            'label': label,
            'album_artist': artist,
            'copyright': copyright_text,
            'composer': composer,
            'lyrics': lyrics_text,
            'isrc': None 
        }
        await set_bandcamp_metadata(file_path, meta_payload)
        # ------------------------
        
        try:
            duration = int(float(track.get('duration') or 0))
        except:
            duration = 0

        downloaded_tracks.append({
            'filepath': file_path,
            'title': track_title,
            'artist': artist,
            'album': album_title,
            'cover': cover_path,
            'duration': duration,
            'quality': '128kbps'
        })

    if not downloaded_tracks:
        raise Exception("Gagal mengunduh track apapun.")

    def get_poster_caption():
        return (
            f"**ᴛɪᴛʟᴇ :** {album_title}\n"
            f"**ᴀʀᴛɪsᴛ :** {artist}\n"
            f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n"
            f"**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
            f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n"
            f"**ǫᴜᴀʟɪᴛʏ :** 128kbps\n"
            f"**ᴘʀᴏᴠɪᴅᴇʀ :** Bandcamp\n"
            f"**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
        )

    if len(downloaded_tracks) == 1 and not is_album:
        track_meta = downloaded_tracks[0]
        track_meta['provider'] = 'Bandcamp'
        track_meta['type'] = 'track'
        await track_upload(track_meta, user)
        await edit_message(msg, "Selesai!")
    else:
        await edit_message(msg, "Memproses Album...")
        _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
        
        zip_path = None
        if is_album_zip:
            await edit_message(msg, "Membuat ZIP...")
            parent_dir = os.path.dirname(dl_dir)
            zip_name = sanitize_filename(album_title)
            base_name = os.path.join(parent_dir, zip_name)
            zip_path = shutil.make_archive(base_name, 'zip', dl_dir)

        if is_art_poster and cover_path:
            try: 
                await send_message(user, cover_path, 'pic', caption=get_poster_caption())
            except Exception as e:
                LOGGER.error(f"Gagal kirim poster: {e}")

        metadata = {
            'type': 'album', 'title': album_title, 'artist': artist,
            'folderpath': dl_dir, 'tracks': downloaded_tracks,
            'cover': cover_path, 'zip_path': zip_path,
            'poster_msg': False,
            'provider': 'Bandcamp',
            'track_count': len(downloaded_tracks), 'quality': '128kbps',
            'release_date': release_date
        }
        await album_upload(metadata, user)
