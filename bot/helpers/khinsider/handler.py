import os
import asyncio
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import ID3, APIC, error
from mutagen.flac import FLAC, Picture

from ...modules.user_settings import bot_set
# Import post_art_poster untuk menampilkan poster manual
from ...helpers.utils import download_file, run_concurrent_tasks, fetch_zip_settings, zip_folder, post_art_poster
from ...helpers.uploder import album_upload
from ...helpers.message import edit_message
from config import Config
from .manager import khinsider_manager

# --- FUNGSI TANAM COVER (Fix Poweramp) ---
def embed_cover(filepath, cover_path, fmt):
    if not cover_path or not os.path.exists(cover_path):
        return

    try:
        if fmt == 'mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except:
                audio = MP3(filepath)
                audio.add_tags()
            
            # Hapus tag gambar lama
            audio.tags.delall("APIC")
            
            with open(cover_path, 'rb') as albumart:
                audio.tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3, 
                    desc=u'Cover',
                    data=albumart.read()
                ))
            audio.save()
            
        elif fmt == 'flac':
            audio = FLAC(filepath)
            image = Picture()
            image.type = 3
            image.mime = 'image/jpeg'
            image.desc = 'Cover'
            with open(cover_path, 'rb') as f:
                image.data = f.read()
            
            audio.clear_pictures()
            audio.add_picture(image)
            audio.save()
            
    except Exception as e:
        print(f"Gagal embed cover: {e}")

# --- HANDLER UTAMA ---
async def start_khinsider(url, user):
    msg = user['bot_msg']
    await edit_message(msg, "Memproses Album Khinsider...")
    
    # 1. Ambil Metadata
    try:
        album_meta = await khinsider_manager.get_album(url)
    except Exception as e:
        await edit_message(msg, f"Gagal mengambil info album: {e}")
        return

    # Buat folder khusus album
    album_folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    os.makedirs(album_folder_path, exist_ok=True)

    # 2. Download Semua Gambar (Fix Lingkaran Merah)
    cover_path = None
    if album_meta.get('images'):
        await edit_message(msg, f"Mengunduh {len(album_meta['images'])} gambar...")
        for i, img_url in enumerate(album_meta['images']):
            try:
                ext = img_url.split('.')[-1].split('?')[0]
                # Gambar pertama jadi cover.jpg, sisanya artwork_X.jpg
                if i == 0:
                    filename = f"cover.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                    cover_path = filepath 
                else:
                    filename = f"artwork_{i}.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                
                await download_file(img_url, filepath)
            except Exception:
                pass

    # 3. Download Lagu
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
            filepath = f"{album_folder_path}/{filename}"
            
            err = await download_file(dl_url, filepath)
            if err:
                raise Exception(err)
            
            # --- FIX: Tanam Cover ke File Musik ---
            if cover_path:
                await asyncio.to_thread(embed_cover, filepath, cover_path, fmt)
            # --------------------------------------
            
            meta = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Game Soundtrack',
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

    # 4. Siapkan Data Upload
    await edit_message(msg, "Memproses upload...")
    
    # Cek Setting ZIP
    _, album_zip, _, _ = await asyncio.to_thread(fetch_zip_settings, user)
    
    zip_path = None
    if album_zip:
        await edit_message(msg, "Mengompresi album ke ZIP...")
        # Zip folder yang berisi lagu DAN semua gambar tadi
        zip_path = await asyncio.to_thread(zip_folder, album_folder_path)
    
    album_data = {
        'title': album_meta['title'],
        'artist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': successful_tracks,
        'cover': cover_path,
        'folderpath': album_folder_path,
        'zip_path': zip_path,
        
        # Data tambahan untuk Art Poster agar sesuai screenshot
        'totaltracks': str(track_total),
        'date': 'N/A', # Khinsider jarang ada tanggal pasti di halaman utama
        'quality': successful_tracks[0]['quality'] if successful_tracks else 'N/A'
    }
    
    # --- FIX: Kirim Art Poster Disini (Manual) ---
    # Karena kita tidak mau mengubah uploder.py, kita panggil fungsi poster di sini
    try:
        await post_art_poster(user, album_data)
    except Exception as e:
        print(f"Gagal kirim poster: {e}")
    # ---------------------------------------------
    
    # Lanjut upload file (ZIP atau Track)
    await album_upload(album_data, user)
