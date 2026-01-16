import os
import asyncio
from ...modules.user_settings import bot_set
from ...helpers.utils import download_file, run_concurrent_tasks, fetch_zip_settings, zip_folder
from ...helpers.uploder import album_upload
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

    # Buat struktur folder: Downloads/UID/AlbumTitle/
    album_folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    os.makedirs(album_folder_path, exist_ok=True)

    # 2. Download Semua Artwork/Gambar (PERBAIKAN ISSUE #2)
    cover_path = None
    images_downloaded = 0
    if album_meta.get('images'):
        await edit_message(msg, f"Mengunduh {len(album_meta['images'])} gambar...")
        for i, img_url in enumerate(album_meta['images']):
            try:
                # Tentukan nama file. Gambar pertama biasanya cover utama.
                # Sisanya diberi nama artwork_1, artwork_2, dll.
                ext = img_url.split('.')[-1].split('?')[0] # handle extension clean
                if i == 0:
                    filename = f"cover.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                    cover_path = filepath # Simpan path cover utama untuk metadata audio
                else:
                    filename = f"artwork_{i}.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                
                # Download gambar ke dalam folder album
                await download_file(img_url, filepath)
                images_downloaded += 1
            except Exception as e:
                # Log error kecil tidak perlu stop proses
                print(f"Gagal download gambar {img_url}: {e}")

    # 3. Siapkan Tugas Download Track
    track_total = len(album_meta['tracks'])
    await edit_message(msg, f"Ditemukan {track_total} lagu.\nAlbum: {album_meta['title']}")

    async def _process_track(track):
        try:
            dl_url, fmt = await khinsider_manager.get_track_download_url(
                track['url'], 
                preferred_formats=[bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'flac'), 'mp3']
            )
            
            filename = f"{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
            filename = filename.replace("/", "_").replace("\\", "_")
            
            # Simpan file audio DI DALAM folder album yang sama dengan gambar
            filepath = f"{album_folder_path}/{filename}"
            
            err = await download_file(dl_url, filepath)
            if err:
                raise Exception(err)
            
            meta = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Khinsider', 
                'tracknumber': track['track_number'],
                'totaltracks': str(track_total),
                'filepath': filepath,
                'cover': cover_path, # Gunakan cover utama yang sudah didownload lokal
                'provider': 'Khinsider',
                'type': 'album',
                'quality': fmt.upper()
            }
            return meta
        except Exception as e:
            return None

    tasks = [_process_track(t) for t in album_meta['tracks']]
    update_details = {
        'msg': msg,
        'title': album_meta['title'],
        'type': 'album',
        'text': "Downloading... {0} {1}/{2}\n{3} ({4})"
    }
    
    results = await run_concurrent_tasks(tasks, update_details, limit=3) 
    successful_tracks = [r for r in results if r]

    if not successful_tracks:
        await edit_message(msg, "Gagal mengunduh semua lagu.")
        return

    # 4. Proses Upload (PERBAIKAN ISSUE #1 - Handling ZIP)
    await edit_message(msg, "Memproses upload...")
    
    # Cek pengaturan ZIP User
    # fetch_zip_settings mengembalikan tuple: (playlist_zip, album_zip, artist_zip, art_poster)
    _, album_zip, _, _ = await asyncio.to_thread(fetch_zip_settings, user)
    
    zip_path = None
    if album_zip:
        await edit_message(msg, "Mengompresi album ke ZIP...")
        # Zip seluruh folder (berisi audio + semua gambar)
        zip_path = await asyncio.to_thread(zip_folder, album_folder_path)
    
    # Bungkus metadata album
    album_data = {
        'title': album_meta['title'],
        'artist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': successful_tracks,
        'cover': cover_path, # Untuk thumbnail upload telegram
        'folderpath': album_folder_path,
        'zip_path': zip_path # Masukkan path zip jika ada
    }
    
    # Fungsi album_upload di uploder.py akan menangani logika:
    # Jika zip_path ada -> Upload File ZIP
    # Jika tidak -> Upload Tracks satu per satu (Batch)
    await album_upload(album_data, user)
