import os
from ...modules.user_settings import bot_set
from ...helpers.utils import download_file, run_concurrent_tasks
from ...helpers.uploder import track_upload, album_upload
from ...helpers.message import edit_message
from config import Config
from .manager import khinsider_manager

async def start_khinsider(url, user):
    msg = user['bot_msg']
    await edit_message(msg, "Memproses Album Khinsider...")
    
    # 1. Ambil Metadata Album
    try:
        album_meta = await khinsider_manager.get_album(url)
    except Exception as e:
        await edit_message(msg, f"Gagal mengambil info album: {e}")
        return

    # 2. Download Cover
    cover_path = None
    if album_meta.get('cover'):
        cover_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/cover.jpg"
        await download_file(album_meta['cover'], cover_path)

    # 3. Siapkan Tugas Download Track
    track_total = len(album_meta['tracks'])
    await edit_message(msg, f"Ditemukan {track_total} lagu.\nAlbum: {album_meta['title']}")

    async def _process_track(track):
        try:
            # Scrape halaman track untuk dapat direct link
            dl_url, fmt = await khinsider_manager.get_track_download_url(
                track['url'], 
                preferred_formats=[bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'flac'), 'mp3']
            )
            
            # Tentukan path file
            filename = f"{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
            # Bersihkan filename
            filename = filename.replace("/", "_").replace("\\", "_")
            
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}/{filename}"
            
            # Download file
            err = await download_file(dl_url, filepath)
            if err:
                raise Exception(err)
            
            # Metadata untuk uploader
            meta = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Khinsider', # Khinsider jarang punya tag artist konsisten di list
                'tracknumber': track['track_number'],
                'totaltracks': str(track_total),
                'filepath': filepath,
                'cover': cover_path,
                'provider': 'Khinsider',
                'type': 'album',
                'quality': fmt.upper()
            }
            return meta
        except Exception as e:
            # Log error tapi jangan stop semua
            return None

    # Jalankan download paralel
    tasks = [_process_track(t) for t in album_meta['tracks']]
    update_details = {
        'msg': msg,
        'title': album_meta['title'],
        'type': 'album',
        'text': "Downloading... {0} {1}/{2}\n{3} ({4})"
    }
    
    results = await run_concurrent_tasks(tasks, update_details, limit=3) # Limit kecil karena scraping halaman track berat

    # Filter hasil sukses
    successful_tracks = [r for r in results if r]

    if not successful_tracks:
        await edit_message(msg, "Gagal mengunduh semua lagu.")
        return

    # 4. Upload
    await edit_message(msg, "Mengunggah ke Telegram...")
    
    # Bungkus metadata album
    album_data = {
        'title': album_meta['title'],
        'artist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': successful_tracks,
        'cover': cover_path,
        'folderpath': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    }
    
    await album_upload(album_data, user)
