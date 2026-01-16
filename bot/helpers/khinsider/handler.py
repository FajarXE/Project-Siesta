import os
import asyncio
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import ID3, APIC, TYER, TDRC, TPOS, TPUB, TXXX
from mutagen.flac import FLAC, Picture

from ...modules.user_settings import bot_set
from ...helpers.utils import download_file, run_concurrent_tasks, fetch_zip_settings, zip_folder, post_art_poster
from ...helpers.uploder import album_upload
from ...helpers.message import edit_message
from config import Config
from .manager import khinsider_manager

# --- FUNGSI TAGGING LENGKAP ---
def set_file_tags(filepath, meta, cover_path, fmt):
    """Menanamkan Cover + Metadata (Year, Disc, Publisher, Date Added) ke file."""
    if not os.path.exists(filepath):
        return

    try:
        # Siapkan data tag
        year = meta.get('date', 'N/A')
        if year == 'N/A': year = None
        
        publisher = meta.get('publisher', 'N/A')
        if publisher == 'N/A': publisher = None
        
        date_added = meta.get('date_added', 'N/A')
        if date_added == 'N/A': date_added = None
        
        disc_num = meta.get('disc_number', '1')
        total_discs = meta.get('totalvolumes', '1')
        disc_set = f"{disc_num}/{total_discs}"

        if fmt == 'mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except:
                audio = MP3(filepath)
                audio.add_tags()
            
            # 1. Embed Cover
            if cover_path and os.path.exists(cover_path):
                audio.tags.delall("APIC")
                with open(cover_path, 'rb') as albumart:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3, desc=u'Cover',
                        data=albumart.read()
                    ))
            
            # 2. Embed Metadata Standar (Year & Disc)
            if year:
                audio.tags.add(TDRC(encoding=3, text=[str(year)])) 
                audio.tags.add(TYER(encoding=3, text=[str(year)])) 
            
            audio.tags.add(TPOS(encoding=3, text=[disc_set])) 
            
            # 3. Embed Publisher, Producer, Label (Mapped from 'Published by')
            if publisher:
                audio.tags.add(TPUB(encoding=3, text=[publisher])) # Publisher Tag Resmi
                # Tambahkan custom text frames untuk Label dan Producer agar muncul di MediaInfo
                audio.tags.add(TXXX(encoding=3, desc='Label', text=[publisher]))
                audio.tags.add(TXXX(encoding=3, desc='Producer', text=[publisher]))
            
            # 4. Embed Date Added
            if date_added:
                audio.tags.add(TXXX(encoding=3, desc='Date Added', text=[date_added]))
            
            audio.save()
            
        elif fmt == 'flac':
            audio = FLAC(filepath)
            
            # 1. Embed Cover
            if cover_path and os.path.exists(cover_path):
                image = Picture()
                image.type = 3
                image.mime = 'image/jpeg'
                image.desc = 'Cover'
                with open(cover_path, 'rb') as f:
                    image.data = f.read()
                audio.clear_pictures()
                audio.add_picture(image)
            
            # 2. Embed Metadata
            if year:
                audio['DATE'] = str(year)
                audio['YEAR'] = str(year)
            
            audio['DISCNUMBER'] = str(disc_num)
            audio['TOTALDISCS'] = str(total_discs)
            
            # 3. Embed Publisher, Producer, Label
            if publisher:
                audio['PUBLISHER'] = publisher
                audio['LABEL'] = publisher
                audio['PRODUCER'] = publisher
                audio['ORGANIZATION'] = publisher # Kadang dibaca sbg Pub
            
            # 4. Embed Date Added
            if date_added:
                audio['DATE_ADDED'] = date_added
            
            audio.save()
            
    except Exception as e:
        print(f"Gagal set tags untuk {filepath}: {e}")

# --- HANDLER UTAMA ---
async def start_khinsider(url, user):
    msg = user['bot_msg']
    await edit_message(msg, "Memproses Album Khinsider...")
    
    # 1. Ambil Metadata Lengkap
    try:
        album_meta = await khinsider_manager.get_album(url)
    except Exception as e:
        await edit_message(msg, f"Gagal mengambil info album: {e}")
        return

    # Folder Output
    album_folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    os.makedirs(album_folder_path, exist_ok=True)

    # 2. Download Gambar
    cover_path = None
    if album_meta.get('images'):
        await edit_message(msg, f"Mengunduh {len(album_meta['images'])} gambar...")
        for i, img_url in enumerate(album_meta['images']):
            try:
                ext = img_url.split('.')[-1].split('?')[0]
                if i == 0:
                    filename = f"cover.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                    cover_path = filepath 
                else:
                    filename = f"artwork_{i}.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                await download_file(img_url, filepath)
            except Exception: pass

    # 3. Download Lagu
    track_total = len(album_meta['tracks'])
    await edit_message(msg, f"Ditemukan {track_total} lagu (Vol: {album_meta['totalvolumes']}).\nAlbum: {album_meta['title']}")

    async def _process_track(track):
        try:
            dl_url, fmt = await khinsider_manager.get_track_download_url(
                track['url'], 
                preferred_formats=[bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'flac'), 'mp3']
            )
            
            # Format nama file: Disc-Track. Title
            if int(album_meta['totalvolumes']) > 1:
                filename = f"{track['disc_number']}-{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
            else:
                filename = f"{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
                
            filename = filename.replace("/", "_").replace("\\", "_")
            filepath = f"{album_folder_path}/{filename}"
            
            err = await download_file(dl_url, filepath)
            if err: raise Exception(err)
            
            # --- FIX: Tanam Metadata + Cover ---
            # Siapkan data meta per track untuk tagging
            track_meta_for_tag = {
                'date': album_meta['date'],
                'disc_number': track['disc_number'],
                'totalvolumes': album_meta['totalvolumes'],
                'publisher': album_meta['publisher'],     # <-- Kirim Publisher
                'date_added': album_meta['date_added']    # <-- Kirim Date Added
            }
            if cover_path:
                await asyncio.to_thread(set_file_tags, filepath, track_meta_for_tag, cover_path, fmt)
            # -----------------------------------
            
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
        except Exception: return None

    tasks = [_process_track(t) for t in album_meta['tracks']]
    update_details = {
        'msg': msg, 'title': album_meta['title'], 'type': 'album',
        'text': "Downloading... {0} {1}/{2}\n{3} ({4})"
    }
    
    results = await run_concurrent_tasks(tasks, update_details, limit=3) 
    successful_tracks = [r for r in results if r]

    if not successful_tracks:
        await edit_message(msg, "Gagal mengunduh semua lagu.")
        return

    # 4. Upload
    await edit_message(msg, "Memproses upload...")
    
    _, album_zip, _, _ = await asyncio.to_thread(fetch_zip_settings, user)
    zip_path = None
    if album_zip:
        await edit_message(msg, "Mengompresi album ke ZIP...")
        zip_path = await asyncio.to_thread(zip_folder, album_folder_path)
    
    # Bungkus Data Album Lengkap untuk Poster
    album_data = {
        'title': album_meta['title'],
        'artist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': successful_tracks,
        'cover': cover_path,
        'folderpath': album_folder_path,
        'zip_path': zip_path,
        
        # --- Metadata Art Poster (Tanpa Publisher/Date Added sesuai request) ---
        'totaltracks': str(track_total),
        'date': album_meta['date'],           
        'totalvolumes': album_meta['totalvolumes'],
        'explicit': str(album_meta['explicit']),
        'quality': successful_tracks[0]['quality'] if successful_tracks else 'N/A'
    }
    
    # Kirim Poster Manual
    try:
        await post_art_poster(user, album_data)
    except Exception as e:
        print(f"Gagal kirim poster: {e}")
    
    await album_upload(album_data, user)
