from pathvalidate import sanitize_filepath
from config import Config
import traceback  # <-- MODIFIKASI: Ditambahkan

from .metadata import *
from .dzapi import deezerapi

from ..utils import *
from ..uploder import *
from ..metadata import set_metadata, get_audio_extension

from ...settings import bot_set
import bot.helpers.translations as lang

# Impor yang sudah diperbaiki dari sebelumnya
from bot.logger import LOGGER
from ..utils import fetch_zip_settings 


async def start_deezer(url:str, user: dict):
    # --- MODIFIKASI DIMULAI (Menambahkan pesan "Selesai") ---
    try:
        media_type, item_id = await deezerapi.custom_url_parse(url)

        if media_type == 'artist':
            await start_artist(item_id, user)
        elif media_type == 'track':
            await start_track(item_id, user, None)
        elif media_type == 'album':
            await start_album(item_id, user)
        elif media_type == 'playlist':
            await start_playlist(item_id, user)
        
        # Kirim pesan "Selesai" HANYA jika fungsi di atas tidak gagal
        await edit_message(user['bot_msg'], lang.s.TASK_COMPLETED)
        
    except Exception as e:
        # Jika terjadi error fatal, laporkan ke pengguna
        LOGGER.error(f"Error fatal di Deezer handler: {e}\n{traceback.format_exc()}")
        await edit_message(user['bot_msg'], f"Error: {e}")
    # --- MODIFIKASI SELESAI ---


async def start_track(item_id: int, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    if not track_meta:
        if int(item_id) < 0: # For user uploaded
            raw_data = await deezerapi.get_track_data(item_id)
        else:
            raw_data = await deezerapi.get_track(item_id)

        raw_data['DATA'] = raw_data['FALLBACK'] if 'FALLBACK' in raw_data.keys() else raw_data['DATA']
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'])
        except Exception as e:
            LOGGER.warning(f"Deezer track {item_id} tidak tersedia: {e}")
            return False # Memberi sinyal kegagalan
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath) # Sanitasi path dasar

    try:
        url = await deezerapi.get_track_url(
            item_id, 
            track_meta['token'], 
            track_meta['token_expiry'], 
            track_meta['quality'])
    except Exception as e:
        LOGGER.warning(f"Gagal mendapatkan URL unduhan Deezer untuk track {item_id}: {e}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename) # Bersihkan nama file

    track_meta['extension'] = 'flac' if track_meta['quality'] == 'FLAC' else 'mp3'

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath # 'filepath' sekarang sudah bersih

    err = await deezerapi.dl_track(item_id, url, track_meta['filepath'])
    if err: # Jika dl_track mengembalikan error
        LOGGER.error(f"Deezer dl_track gagal untuk {item_id}: {err}")
        return False

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Deezer (download_file gagal diam-diam?): {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Deezer untuk {filepath}: {e}")
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)
        # Hapus pesan "Selesai" dari sini, biarkan start_deezer yang menangani
        # await edit_message(user['bot_msg'], lang.s.TASK_COMPLETED)

    return True


async def start_album(album_id:int, user:dict, upload=True):
    try:
        raw_data = await deezerapi.get_album(album_id)
    except Exception as e:
        # Angkat error agar start_deezer bisa menangkapnya
        raise Exception(f"Gagal mendapatkan metadata album Deezer: {e}")

    album_meta = await process_album_metadata(album_id, raw_data['DATA'], raw_data['SONGS'], user['r_id'])
    
    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # concurrent
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    # --- MODIFIKASI DIMULAI (Menyaring lagu gagal) ---
    task_results = await run_concurrent_tasks(tasks, update_details)

    original_tracks = album_meta['tracks']
    successful_tracks = []
    
    for i in range(len(original_tracks)):
        if i < len(task_results) and task_results[i]: # Jika task berhasil (True)
            successful_tracks.append(original_tracks[i])
        else:
            LOGGER.info(f"Melewatkan track Deezer {original_tracks[i].get('title', 'N/A')} karena gagal diunduh (ditangani).")

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        # Jangan kirim pesan error, cukup angkat error agar start_deezer tahu
        raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh untuk album {album_meta['title']}.")

    # Periksa pengaturan zip PENGGUNA
    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: # Gunakan variabel dari fetch_zip_settings
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['folderpath'] = await zip_handler(album_meta['folderpath'])
    # --- MODIFIKASI SELESAI ---

    # Upload
    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
    
    # Hapus pesan "Selesai" dari sini, biarkan start_deezer yang menangani


async def start_artist(artist_id, user):
    album_ids = await deezerapi.get_artist_album_ids(artist_id, 0, -1, False)

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)
    
    # Ambil pengaturan zip artis dari pengguna, jika tidak ada, gunakan default
    artist_zip = user.get("artist_zip", bot_set.artist_zip) 

    upload_album = True
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    
    if artist_zip: 
        upload_album = False 

    for album in album_ids:
        await start_album(album, user, upload_album)
    
    # Hapus pesan "Selesai" dari sini, biarkan start_deezer yang menangani


async def start_playlist(playlist_id, user):
    raw_data = await deezerapi.get_playlist(playlist_id, -1, 0)

    play_meta = await process_playlist_meta(raw_data, user['r_id'])

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/"

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)
    
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder += f"{play_meta['title']}"
        playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder


    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }

    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    upload = True
    
    # --- MODIFIKASI DIMULAI (Menyaring lagu gagal) ---
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
        play_meta['tracks'] = successful_tracks
        play_meta['totaltracks'] = len(successful_tracks) # Perbarui jumlah

    else:
        i = 0
        if playlist_zip: upload = False 
        successful_tracks_non_conc = []
        for track in play_meta['tracks']:
            await progress_message(i, len(play_meta['tracks']), update_details)
            success = await start_track(track['itemid'], user, track, upload, playlist_folder, bot_set.disable_sort_link)
            if success:
                successful_tracks_non_conc.append(track)
            i+=1
        play_meta['tracks'] = successful_tracks_non_conc
        play_meta['totaltracks'] = len(successful_tracks_non_conc) # Perbarui jumlah
    # --- MODIFIKASI SELESAI ---
    
    if not play_meta['tracks']:
         raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh untuk playlist {play_meta['title']}.")

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        if playlist_sort:
            play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        play_meta['folderpath'] = await zip_handler(play_meta['folderpath'])

    if not upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)

    # Hapus pesan "Selesai" dari sini, biarkan start_deezer yang menangani
