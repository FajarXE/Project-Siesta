# [GANTI FILE: bot/helpers/qobuz/handler.py]

import shutil
import os
import traceback
from .utils import *
from config import Config
from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata
from ..message import edit_message
from bot.logger import LOGGER

# [FIX] Import bot_set dengan benar (Absolute Import)
from bot.settings import bot_set 

from ..uploder import track_upload, album_upload, artist_upload, playlist_upload

# --- IMPORTS BARU UNTUK CUSTOM TAGS ---
try:
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TXXX
except ImportError:
    FLAC = None
    ID3 = None
    LOGGER.warning("Mutagen tidak terinstall. Custom tags mungkin tidak tersimpan.")
# --------------------------------------

# Exception kustom
try:
    from .utils import QobuzContentUnavailableError
except ImportError:
    class QobuzContentUnavailableError(Exception):
        pass

async def force_custom_tags(filepath, metadata):
    if not os.path.exists(filepath): return
    ext = filepath.split('.')[-1].lower()
    target_keys = ['creation_time', 'RELEASETIME', 'ORIGINALDATE']
    tags_to_write = {k: str(metadata[k]) for k in target_keys if metadata.get(k)}
    if not tags_to_write: return

    try:
        if ext == 'flac' and FLAC:
            try:
                audio = FLAC(filepath)
                for k, v in tags_to_write.items(): audio[k] = v
                audio.save()
            except: pass
        elif ext == 'mp3' and ID3:
            try:
                try: audio = ID3(filepath)
                except: audio = ID3(); audio.save(filepath)
                for k, v in tags_to_write.items(): audio.add(TXXX(encoding=3, desc=k, text=v))
                audio.save()
            except: pass
    except: pass

async def start_qobuz(url:str, user:dict):
    clients_list = user.get('qobuz_clients_list', [])
    if not clients_list:
        return await edit_message(user['bot_msg'], "Kesalahan: Tidak ada daftar klien Qobuz.")

    last_error = "Tidak ada error"
    
    # Loop Akun hanya jika GAGAL TOTAL mengambil info awal.
    for i, client in enumerate(clients_list):
        user['qobuz_api'] = client
        client_label = client.label or client.user_id 
        try:
            await edit_message(user['bot_msg'], f"Mencoba Akun #{i+1}/{len(clients_list)} ({client_label})...")
            
            items, item_id, type_dict, content = await check_type(url, user)
            
            if items is None and item_id is None:
                 raise QobuzContentUnavailableError("Gagal mendapatkan item/ID valid.")

            # Jika berhasil dapat konten, jalankan proses download
            if items is not None:
                if not items:
                    await edit_message(user['bot_msg'], f"Playlist/Artis kosong.")
                    return 
                if type_dict['iterable_key'] == 'albums': 
                    await start_artist(items, user, content)
                else: 
                    await start_playlist(items, content, user)
            else:
                if type_dict.get("album") is True: await start_album(item_id, user)
                elif type_dict.get("album") is False: await start_track(item_id, user, None)
                else: raise Exception(f"Tipe konten tidak diketahui.")
            
            # [PENTING] Jika sampai sini, berarti sukses. Return agar tidak loop ke akun lain.
            await edit_message(user['bot_msg'], f"Selesai memproses dengan Akun {client_label}.")
            return 

        except QobuzContentUnavailableError as e:
            # Error spesifik konten (misal region lock), coba akun lain
            last_error = f"{e}"
            LOGGER.warning(f"Akun {client_label} gagal mengambil metadata: {e}")
            continue 
        except Exception as e:
            # Error coding/fatal lainnya
            last_error = f"{e}"
            LOGGER.error(f"Fatal Error Qobuz (Start): {e}\n{traceback.format_exc()}")
            break 

    try: await edit_message(user['bot_msg'], f"Gagal: {last_error}")
    except: pass

async def start_album(item_id:int, user:dict, upload=True, basefolder=None):
    client = user['qobuz_api']
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err: return await send_message(user, err)
    
    try: track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)
    except: 
        # Coba track kedua jika track pertama error (fallback)
        try: track_meta = await client.get_track_url(album_meta['tracks'][1]['itemid'], user)
        except: raise QobuzContentUnavailableError(f"Gagal mendapatkan URL track sampel album.")
            
    _, album_meta['quality'] = await get_quality(track_meta, user)
    
    if upload: album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    album_folder = basefolder + f"/{album_meta['title']}" if basefolder else f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))
        
    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': album_meta['title'], 'type': album_meta['type']}
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [album_meta['tracks'][i] for i, res in enumerate(task_results) if res]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks: return

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    # Booklet Logic
    booklet_path = None
    if album_meta.get('booklet_url'):
        try:
            temp_path = os.path.join(album_meta['folderpath'], "Booklet.pdf")
            if not await download_file(album_meta['booklet_url'], temp_path): booklet_path = temp_path
        except: pass

    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try: shutil.copy2(album_meta['cover'], os.path.join(album_meta['folderpath'], "cover.jpg"))
        except: pass

    if album_zip: 
        await edit_message(user['bot_msg'], f"Zipping {album_meta['totaltracks']} tracks...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
    elif booklet_path and os.path.exists(booklet_path):
        try: await user['bot_msg'].reply_document(document=booklet_path, caption="Booklet", file_name=f"Booklet.pdf")
        except: pass

    if upload: await album_upload(album_meta, user)

async def start_track(item_id:int, user:dict, track_meta:dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    client = user['qobuz_api']

    if not track_meta:
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err: return await send_message(user, err)
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)
    else: filepath = basefolder
    
    # [FIX] Anti-Crash: Tangkap error URL di sini
    try:
        raw_data = await client.get_track_url(item_id, user)
        url = raw_data['url']
    except Exception as e:
        LOGGER.warning(f"Gagal mendapatkan URL Track ID {item_id}: {e}. Skipping...")
        return False # Return False agar loop playlist lanjut ke lagu berikutnya
        
    try:
        track_meta['extension'], track_meta['quality'] = await get_quality(raw_data, user)
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        full_path = f"{filepath}/{sanitize_filepath(raw_filename)}.{track_meta['extension']}"
        track_meta['filepath'] = full_path

        if await download_file(url, full_path): return False
        
        await set_metadata(track_meta, user['user_id'])
        await force_custom_tags(full_path, track_meta)
        
        if upload: 
            await track_upload(track_meta, user, disable_link)
            
        return True
    except Exception as e:
        LOGGER.error(f"Error processing track {item_id}: {e}")
        return False

async def start_artist(albums, user, artist):
    artist_meta = await get_artist_meta(artist[0])
    artist_meta['folderpath'] = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{artist[0]['name']}")

    upload_album = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if bot_set.artist_batch: upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: upload_album = False 

    for album in albums: await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        if artist_zip: 
            await edit_message(user['bot_msg'], f"Zipping artist...")
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)


async def start_playlist(tracks, playlist, user):
    client = user['qobuz_api']
    play_meta = await get_playlist_meta(playlist[0], tracks, user['r_id'], user)
    
    playlist_folder = None
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{play_meta['title']}")
    play_meta['folderpath'] = playlist_folder
    
    # Coba ambil sampel kualitas, jika gagal jangan crash playlist
    try:
        track_meta = await client.get_track_url(tracks[0]['id'], user)
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except:
        play_meta['quality'] = "Unknown"

    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': play_meta['title'], 'type': play_meta['type']}
    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    # --- [FIX DETEKSI MODE] ---
    upload = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    # Cek Mode User dengan Aman
    user_id = user.get('user_id')
    raw_user_data = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
    user_mode = raw_user_data.get('upload_mode', 'Telegram')
    
    # Jika mode Cloud, matikan upload per track
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        upload = False
        LOGGER.info(f"Mode Cloud ({user_mode}) terdeteksi. Mematikan upload per-track.")

    # Logic Concurrent vs Serial
    if bot_set.playlist_conc:
        upload = False # Concurrent selalu batch upload
        tasks = []
        for track in play_meta['tracks']: 
            tasks.append(start_track(track['itemid'], user, track, upload, playlist_folder))
        
        task_results = await run_concurrent_tasks(tasks, update_details)
        successful_tracks = [play_meta['tracks'][i] for i, res in enumerate(task_results) if res]
        play_meta['tracks'] = successful_tracks
        play_meta['totaltracks'] = len(successful_tracks)
    else:
        i = 0
        if playlist_zip: upload = False
        successful_tracks_non_conc = []
        for track in play_meta['tracks']:
            await progress_message(i, len(play_meta['tracks']), update_details)
            # start_track sekarang aman, tidak akan raise Exception jika gagal
            success = await start_track(track['itemid'], user, track, upload, playlist_folder, bot_set.disable_sort_link, True)
            if success: 
                successful_tracks_non_conc.append(track)
            i+=1
        play_meta['tracks'] = successful_tracks_non_conc
        play_meta['totaltracks'] = len(successful_tracks_non_conc)

    # Copy Cover
    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try: shutil.copy2(play_meta['cover'], os.path.join(play_meta['folderpath'], "cover.jpg"))
        except: pass

    # Zip Handler
    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Zipping {play_meta['totaltracks']} tracks...")
        if playlist_sort: play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
       
    # --- [FIX FINAL] Panggil Upload Batch jika mode upload per track mati ---
    if not upload:
        if not play_meta['tracks']:
            await edit_message(user['bot_msg'], "Gagal: Tidak ada lagu yang berhasil diunduh.")
            return
            
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        # Ini akan memanggil playlist_upload di uploder.py (yang sudah support Gofile Folder)
        await playlist_upload(play_meta, user)
