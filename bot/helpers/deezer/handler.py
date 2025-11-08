# [GANTI FILE: bot/helpers/deezer/handler.py]

from pathvalidate import sanitize_filepath
from config import Config
import traceback
import os # <--- Impor os

from .metadata import *
# --- MODIFIKASI: Hapus impor global ---
# from .dzapi import deezerapi 
# --- BATAS MODIFIKASI ---

from ..utils import *
from ..uploder import *
from ..metadata import set_metadata, get_audio_extension

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER 
from ..utils import fetch_zip_settings 
from ..message import edit_message


async def start_deezer(url:str, user: dict):
    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user.get('deezer_api')
    if not deezerapi:
        await edit_message(user['bot_msg'], "Error: Sesi login Deezer tidak ditemukan untuk pengguna ini.")
        return
    # --- BATAS MODIFIKASI ---

    try:
        media_type, item_id, _ = custom_url_parse(url)

        if media_type == 'artist':
            await start_artist(item_id, user)
        elif media_type == 'track':
            # --- MODIFIKASI: Kirim 'user' ke start_track ---
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        elif media_type == 'album':
            # --- MODIFIKASI: Kirim 'user' ke start_album ---
            await start_album(item_id, user)
        elif media_type == 'playlist':
            # --- MODIFIKASI: Kirim 'user' ke start_playlist ---
            await start_playlist(item_id, user)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Deezer handler: {e}\n{traceback.format_exc()}")
        # Jika ini adalah DeezerError, tampilkan pesan yang bersih
        if isinstance(e, DeezerError):
             await edit_message(user['bot_msg'], f"Tugas Gagal: {e}")
        else:
            await edit_message(user['bot_msg'], f"Error Deezer: {e}")


async def start_track(item_id: int, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user['deezer_api']
    # --- BATAS MODIFIKASI ---

    if not track_meta:
        try:
            # --- MODIFIKASI: Teruskan 'user' ke process_track_metadata ---
            track_meta = await process_track_metadata(item_id, user['r_id'], user=user)
        except Exception as e:
            LOGGER.warning(f"Deezer track {item_id} tidak tersedia: {e}")
            # Lempar error agar retry ARL tahu
            if "not available" in str(e).lower():
                raise DeezerError(f"Track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    try:
        # --- PERBAIKAN: Gunakan 'get_track_url' yang baru ---
        url = await deezerapi.get_track_url(
            track_meta, # Berikan seluruh track_meta
            track_meta['quality'])
    except Exception as e:
        LOGGER.warning(f"Gagal mendapatkan URL unduhan Deezer untuk track {item_id}: {e}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    track_meta['extension'] = 'flac' if track_meta['quality'] == 'FLAC' else 'mp3'

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- MODIFIKASI: Panggil dl_track dari instans pengguna ---
    err = await deezerapi.dl_track(url, track_meta['filepath'])
    if err:
        LOGGER.error(f"Deezer dl_track gagal untuk {item_id}: {err}")
        return False

    try:
        await set_metadata(track_meta)
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Deezer: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Deezer: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album(album_id:int, user:dict, upload=True, basefolder=None):
    deezerapi = user['deezer_api']

    try:
        # Ambil data album DAN track dalam satu panggilan API
        album_data = await deezerapi.get_album(album_id)
        # --- PERBAIKAN: Gunakan get_album_tracks ---
        tracklist_raw_data = await deezerapi.get_album_tracks(album_id)
        # --- AKHIR PERBAIKAN ---
        
    except Exception as e:
        # Jika ini adalah error 'not available', lempar untuk retry ARL
        if "not available" in str(e).lower():
             raise DeezerError(f"Album {album_id} tidak tersedia: {e}")
        raise Exception(f"Gagal mendapatkan metadata album Deezer: {e}")

    # --- PERBAIKAN: Gunakan 'tracklist_raw_data' ---
    songs_dict = tracklist_raw_data
    # --- AKHIR PERBAIKAN ---

    if not songs_dict or not songs_dict.get('data'):
        album_title = album_data.get('TITLE', f'(ID: {album_id})')
        raise Exception(f"Album '{album_title}' tidak memiliki daftar lagu ('data' key missing or empty from API response).")
    
    album_meta = await process_album_metadata(album_id, album_data, songs_dict, user['r_id'], user=user)
    
    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

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
            LOGGER.info(f"Melewatkan track Deezer {original_tracks[i].get('title', 'N/A')} karena gagal diunduh (ditangani).")

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_artist(artist_id, user):
    deezerapi = user['deezer_api']
    
    try:
        artist_data = await deezerapi.get_artist(artist_id)
        # Fallback sederhana jika fungsi process_artist_metadata tidak ada:
        artist_meta = {
            "provider": "Deezer",
            "artist": artist_data.get("name", "Unknown Artist"),
            "folderpath": sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Deezer/{artist_data.get('name', 'Unknown Artist')}")
        }
        
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata artist Deezer: {e}")

    # --- PERBAIKAN: Gunakan 'get_artist_albums' ---
    album_ids = await deezerapi.get_artist_albums(artist_id) # Asumsikan ini mengambil ID
    # --- AKHIR PERBAIKAN ---
    
    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)
    artist_zip = bot_set.user_data.get(user.get("user_id", 0), {}).get("artist_zip", bot_set.artist_zip)
    
    upload_album = not artist_zip

    for album_id in album_ids:
        try:
            await start_album(album_id, user, upload_album, basefolder=artist_meta['folderpath'])
        except Exception as e:
            LOGGER.warning(f"Gagal mengunduh album {album_id} untuk artis {artist_id}: {e}")
            continue # Lanjutkan ke album berikutnya

    if artist_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)


async def start_playlist(playlist_id, user):
    """
    Versi start_playlist yang disederhanakan dan diperbaiki.
    """
    deezerapi = user['deezer_api']
    
    try:
        # --- PERBAIKAN: Gunakan panggilan API yang benar ---
        raw_data = await deezerapi.get_playlist(playlist_id, -1, 0)
        # --- AKHIR PERBAIKAN ---
        if not raw_data.get('SONGS') or not raw_data.get('SONGS').get('data'):
             raise DeezerError(f"Playlist {playlist_id} tidak tersedia atau kosong (mungkin terkunci regional?).")
    except Exception as e:
        LOGGER.error(f"Gagal mengambil data playlist Deezer {playlist_id}: {e}")
        if "not available" in str(e).lower():
            raise DeezerError(f"Playlist {playlist_id} tidak tersedia: {e}")
        raise e

    play_meta = await process_playlist_meta(raw_data, user['r_id'], user=user)

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/{play_meta['title']}"
    playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder

    playlist_zip, art_poster, album_zip = fetch_zip_settings(user)

    if art_poster:
        play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    tasks = []
    for track in play_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder)) 

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)

    original_tracks = play_meta['tracks']
    successful_tracks = []
    for i in range(len(original_tracks)):
        if i < len(task_results) and task_results[i]:
            successful_tracks.append(original_tracks[i])
    
    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)

    if not play_meta['tracks']:
         raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh untuk playlist {play_meta['title']}.")

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
    else:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
