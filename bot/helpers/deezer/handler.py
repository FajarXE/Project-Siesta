# [GANTI FILE: bot/helpers/deezer/handler.py]

from pathvalidate import sanitize_filepath
from config import Config
import traceback
import os 

from .metadata import *

from ..utils import *
from ..uploder import *
from ..metadata import set_metadata, get_audio_extension

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER 
from ..utils import fetch_zip_settings 
from ..message import edit_message

# --- TAMBAHAN BARU: IMPOR MANAGER LIRIK ---
try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None
# --- BATAS TAMBAHAN ---


async def start_deezer(url:str, user: dict):
    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user.get('deezer_api')
    if not deezerapi:
        await edit_message(user['bot_msg'], "Error: Sesi login Deezer tidak ditemukan untuk pengguna ini.")
        raise Exception("Sesi login Deezer tidak ditemukan.") 
    # --- BATAS MODIFIKASI ---

    # --- PERBAIKAN: Hapus blok Try/Except luas ---
    # Membiarkan error naik ke download.py agar ARL bisa di-switch jika terkena region lock
    
    media_type, item_id = await deezerapi.custom_url_parse(url)

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
            # Raise error agar ditangkap logic retry di download.py
            raise e 
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

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
    safe_filename = sanitize_filepath(raw_filename)

    track_meta['extension'] = 'flac' if track_meta['quality'] == 'FLAC' else 'mp3'

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- MODIFIKASI: Panggil dl_track dari instans pengguna ---
    err = await deezerapi.dl_track(item_id, url, track_meta['filepath'])
    if err:
        LOGGER.error(f"Deezer dl_track gagal untuk {item_id}: {err}")
        return False

    # --- PERBAIKAN VALIDASI UKURAN FILE ---
    # Batas 1 MB. Jika di bawah ini, hapus diam-diam.
    if not os.path.exists(track_meta['filepath']) or os.path.getsize(track_meta['filepath']) < 1048576: 
        LOGGER.warning(f"Deezer: File unduhan korup/kecil (<1MB). Mengulang dengan akun lain...")
        try:
            os.remove(track_meta['filepath'])
        except: pass
        return False
    # --- BATAS PERBAIKAN ---

    try:
        # --- MODIFIKASI PENTING: Kirim user_id ke set_metadata agar lirik diambil ---
        await set_metadata(track_meta, user['user_id'])
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Deezer: {filepath}")
        return False
    except Exception:
        # --- PERBAIKAN LOG: SILENT MODE ---
        LOGGER.warning(f"Deezer: Metadata gagal (File unduhan invalid). Mengulang dengan akun lain...")
        try:
            os.remove(track_meta['filepath'])
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album(album_id:int, user:dict, upload=True, basefolder=None): 
    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user['deezer_api']
    # --- BATAS MODIFIKASI ---

    try:
        album_metadata_dict = await deezerapi.get_album(album_id)
        tracklist_raw_data = await deezerapi.get_album_tracks(album_id)
        
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Deezer: {e}")

    songs_dict = tracklist_raw_data.get('SONGS')

    if not songs_dict or not songs_dict.get('data'):
        album_title = album_metadata_dict.get('ALB_TITLE', f'(ID: {album_id})')
        raise Exception(f"Album '{album_title}' tidak memiliki daftar lagu ('SONGS' key missing or empty from API response).")
    
    # --- MODIFIKASI: Teruskan 'user' ke process_album_metadata ---
    album_meta = await process_album_metadata(album_id, album_metadata_dict, songs_dict, user['r_id'], user=user)
    # --- BATAS MODIFIKASI ---
    
    # --- PERBAIKAN: Gunakan 'basefolder' jika ada (untuk Artist) ---
    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    # --- AKHIR PERBAIKAN ---
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        # --- PERBAIKAN BARU: REUSE POSTER (GUNAKAN KEMBALI) ---
        # Cek apakah poster untuk album ini sudah ada di sesi user (karena retry)
        poster_key = f'poster_album_{album_id}'
        existing_poster = user.get(poster_key)
        
        if existing_poster:
            # Gunakan yang sudah ada, jangan kirim baru (Anti-Spam)
            album_meta['poster_msg'] = existing_poster
        else:
            # Kirim baru dan simpan di memori user
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
            user[poster_key] = album_meta['poster_msg']
        # ------------------------------------------------------

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
        # --- PENTING: JANGAN HAPUS POSTER DI SINI ---
        # Kita biarkan poster tetap ada agar bisa digunakan lagi oleh Akun berikutnya
        
        # Trigger Retry Exception
        raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh (Track not available) untuk album {album_meta['title']}.")

    # --- PERBAIKAN: Unpack 4 nilai (urutan baru) ---
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        # --- PERBAIKAN: Gunakan 'zip_path' agar konsisten ---
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_artist(artist_id, user):
    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user['deezer_api']
    # --- BATAS MODIFIKASI ---
    
    # --- PERBAIKAN: Dapatkan metadata artist dulu ---
    try:
        artist_data = await deezerapi.get_artist(artist_id)
        artist_meta = await process_artist_metadata(artist_data, user['r_id'])
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata artist Deezer: {e}")
    # --- AKHIR PERBAIKAN ---

    album_ids = await deezerapi.get_artist_album_ids(artist_id, 0, -1, False)
    
    # --- PERBAIKAN: Pindahkan artist_meta['folderpath'] ke sini ---
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath'])
    # --- AKHIR PERBAIKAN ---

    # --- PERBAIKAN: Unpack 4 nilai dan gunakan 'artist_zip' yang benar ---
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---
    
    upload_album = True
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: 
        upload_album = False 
    for album in album_ids:
        # --- PERBAIKAN: Teruskan 'artist_meta['folderpath']' sebagai basefolder ---
        await start_album(album, user, upload_album, basefolder=artist_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    # --- PERBAIKAN: Tambahkan logika upload artist ---
    if not upload_album:
        if artist_zip:
            await edit_message(user['bot_msg'], lang.s.ZIPPING)
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])

        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)
    # --- AKHIR PERBAIKAN ---


async def start_playlist(playlist_id, user):
    # --- MODIFIKASI: Dapatkan klien API dari kamus user ---
    deezerapi = user['deezer_api']
    # --- BATAS MODIFIKASI ---
    
    raw_data = await deezerapi.get_playlist(playlist_id, -1, 0)
    
    # --- MODIFIKASI: Teruskan 'user' ke process_playlist_meta ---
    play_meta = await process_playlist_meta(raw_data, user['r_id'], user=user)
    # --- BATAS MODIFIKASI ---

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/"
    
    # --- PERBAIKAN: Unpack 4 nilai (urutan baru) ---
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---
    
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

    # --- PERBAIKAN BARU: REUSE POSTER (GUNAKAN KEMBALI) ---
    upload = True
    poster_key = f'poster_playlist_{playlist_id}'
    existing_poster = user.get(poster_key)

    if upload:
        if existing_poster:
            play_meta['poster_msg'] = existing_poster
        else:
            play_meta['poster_msg'] = await post_art_poster(user, play_meta)
            user[poster_key] = play_meta['poster_msg']
    # ------------------------------------------------------
    
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
        play_meta['totaltracks'] = len(successful_tracks)

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
        play_meta['totaltracks'] = len(successful_tracks_non_conc)
    
    if not play_meta['tracks']:
         # Trigger Retry Exception
         raise Exception(f"Tidak ada lagu Deezer yang berhasil diunduh (Track not available) untuk playlist {play_meta['title']}.")

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        if playlist_sort:
            play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        # --- PERBAIKAN: Gunakan 'zip_path' agar konsisten ---
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    if not upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
