# [GANTI FILE: bot/helpers/qobuz/handler.py]

import shutil
from .utils import *
from config import Config

from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata
from ..message import edit_message
from bot.logger import LOGGER
import traceback

from ..uploder import track_upload, album_upload, artist_upload, playlist_upload

# Exception kustom (pastikan diimpor dari utils.py atau didefinisikan)
try:
    from .utils import QobuzContentUnavailableError
except ImportError:
    class QobuzContentUnavailableError(Exception):
        pass


async def start_qobuz(url:str, user:dict):
    
    clients_list = user.get('qobuz_clients_list', [])
    if not clients_list:
        return await edit_message(user['bot_msg'], "Kesalahan: Tidak ada daftar klien Qobuz yang ditemukan.")

    last_error = "Tidak ada error"
    
    for i, client in enumerate(clients_list):
        user['qobuz_api'] = client
        client_label = client.label or client.user_id 
        
        try:
            await edit_message(user['bot_msg'], f"Mencoba Akun #{i+1}/{len(clients_list)} ({client_label})...")

            items, item_id, type_dict, content = await check_type(url, user)
            
            if items is None and item_id is None:
                 raise QobuzContentUnavailableError("Gagal mendapatkan item atau ID yang valid dari tautan.")

            if items:
                if type_dict['iterable_key'] == 'albums':
                    await start_artist(items, user, content)
                else:
                    await start_playlist(items, content, user)
            else:
                # --- PERBAIKAN: Ganti type_dict["album"] menjadi .get("album") ---
                # Ini adalah perbaikan untuk KeyError: 'album' saat tautan adalah 'interpreter'
                if type_dict.get("album") is True:
                    await start_album(item_id, user)
                elif type_dict.get("album") is False:
                    await start_track(item_id, user, None)
                else:
                    # Ini seharusnya tidak terjadi jika check_type() berfungsi
                    raise Exception(f"Tipe konten tidak diketahui: {type_dict}")
                # --- BATAS PERBAIKAN ---
            
            await edit_message(user['bot_msg'], f"Sukses mengunduh dengan Akun {client_label}!")
            return 

        except QobuzContentUnavailableError as e:
            last_error = f"Akun {client_label}: Konten tidak tersedia. ({e})"
            LOGGER.info(last_error) 
            continue 

        except Exception as e:
            # Ini menangkap KeyError atau error fatal lain
            last_error = f"Error fatal di Akun {client_label}: {e}"
            LOGGER.error(f"{last_error}\n{traceback.format_exc()}")
            break # Hentikan loop jika terjadi error fatal (seperti KeyError)

    try:
        await edit_message(user['bot_msg'], f"Semua {len(clients_list)} akun Qobuz gagal.\nKesalahan terakhir: {last_error}")
    except Exception as e:
        LOGGER.error(f"FATAL: Gagal mengirim pesan 'Semua akun gagal' ke pengguna. Error: {e}")


async def start_album(item_id:int, user:dict, upload=True, basefolder=None):
    client = user['qobuz_api']
    
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err:
        if err == "UNAVAILABLE":
            raise QobuzContentUnavailableError("Album tidak streamable.")
        return await send_message(user, err)
    
    try:
        track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)
    except KeyError:
         raise QobuzContentUnavailableError(f"Track pertama album {item_id} tidak memiliki URL.")

    _, album_meta['quality'] = await get_quality(track_meta, user)
    
    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))
        
    
    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    original_tracks = album_meta['tracks']
    successful_tracks = []
    
    for i in range(len(original_tracks)):
        if i < len(task_results) and task_results[i]:
            successful_tracks.append(original_tracks[i])
        else:
            LOGGER.warning(f"Melewatkan track {original_tracks[i].get('title', 'N/A')} karena gagal diunduh.")

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        LOGGER.error(f"Tidak ada lagu yang berhasil diunduh untuk album {album_meta['title']}.")
        return

    # --- PERBAIKAN: Ambil 'album_zip' (item ke-3 / indeks 2) ---
    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---
    
    if album_zip: # <-- Sekarang ini menggunakan variabel yang benar
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        # --- PERBAIKAN: Gunakan 'zip_path' untuk Qobuz juga agar konsisten ---
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    if upload:
        await album_upload(album_meta, user)


async def start_track(item_id:int, user:dict, track_meta:dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    client = user['qobuz_api']

    if not track_meta:
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err:
            if err == "UNAVAILABLE":
                raise QobuzContentUnavailableError(f"Track {item_id} tidak streamable.")
            return await send_message(user, err)
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)
    else:
        filepath = basefolder
    
    try:
        raw_data = await client.get_track_url(item_id, user)
        url = raw_data['url']
    except KeyError:
        raise QobuzContentUnavailableError(f"Track {item_id} tidak memiliki URL (KeyError).")
        
    track_meta['extension'], track_meta['quality'] = await get_quality(raw_data, user)

    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)
    full_path = f"{filepath}/{safe_filename}.{track_meta['extension']}"

    track_meta['filepath'] = full_path

    err = await download_file(url, full_path)
    if err:
        LOGGER.error(f"Download_file gagal untuk {full_path}: {err}")
        return False
    
    try:
        await set_metadata(track_meta)

        if upload:
            await track_upload(track_meta, user, disable_link)
            
        return True

    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download (download_file gagal diam-diam?): {full_path}")
        return False

    except Exception as e:
        LOGGER.error(f"Gagal memproses (metadata/upload) untuk {full_path}: {e}\n{traceback.format_exc()}")
        return False


async def start_artist(albums, user, artist):
    artist_meta = await get_artist_meta(artist[0])
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{artist[0]['name']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath'])

    upload_album = True
    
    # --- PERBAIKAN: Ambil pengaturan zip artis dari bot_set (karena tidak ada per-user) ---
    artist_zip = bot_set.artist_zip 
    # --- AKHIR PERBAIKAN ---
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: # <-- Gunakan variabel yang benar
        upload_album = False 

    for album in albums:
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        if artist_zip: # <-- Gunakan variabel yang benar
            await edit_message(user['bot_msg'], f"Menyiapkan folder artis {artist_meta['title']} menjadi .zip...")
            # --- PERBAIKAN: Gunakan 'zip_path' untuk Qobuz juga ---
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
            # --- AKHIR PERBAIKAN ---
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)


async def start_playlist(tracks, playlist, user):
    client = user['qobuz_api']
    
    play_meta = await get_playlist_meta(playlist[0], tracks, user['r_id'], user)
    
    playlist_folder = None
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{play_meta['title']}"
        playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder
    
    try:
        track_meta = await client.get_track_url(tracks[0]['id'], user)
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except KeyError:
        raise QobuzContentUnavailableError(f"Track pertama playlist {tracks[0]['id']} tidak memiliki URL.")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }

    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    upload = True
    # --- PERBAIKAN: Ambil 'playlist_zip' (item ke-1 / indeks 0) ---
    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---
    
    if bot_set.playlist_conc:
        upload = False
        tasks = []
        for track in play_meta['tracks']:
            tasks.append(start_track(track['itemid'], user, track, upload, playlist_folder))
        
        task_results = await run_concurrent_tasks(tasks, update_details)
        original_tracks = play_meta['tracks']
        successful_tracks = []
        for i in range(len(original_tracks)):
            if i < len(task_results) and task_results[i]:
                successful_tracks.append(original_tracks[i])
            else:
                LOGGER.info(f"Melewatkan track {original_tracks[i].get('title', 'N/A')} di playlist karena gagal diunduh (ditangani).")
                
        play_meta['tracks'] = successful_tracks
        play_meta['totaltracks'] = len(successful_tracks)

    else:
        i = 0
        if playlist_zip:
            upload = False
        successful_tracks_non_conc = []
        for track in play_meta['tracks']:
            await progress_message(i, len(play_meta['tracks']), update_details)
            success = await start_track(track['itemid'], user, track, upload, playlist_folder, bot_set.disable_sort_link, True)
            if success:
                successful_tracks_non_conc.append(track)
            i+=1
        play_meta['tracks'] = successful_tracks_non_conc
        play_meta['totaltracks'] = len(successful_tracks_non_conc)

    if playlist_zip: # <-- Sekarang menggunakan variabel yang benar
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        if playlist_sort:
            play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        # --- PERBAIKAN: Gunakan 'zip_path' untuk Qobuz juga ---
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---
       
    if not upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
