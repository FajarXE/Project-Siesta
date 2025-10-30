import shutil
from .utils import *
from config import Config

from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata
from ..message import edit_message  # Pastikan edit_message diimpor
from bot.logger import LOGGER      # Impor LOGGER
import traceback                  # Impor traceback

from ..uploder import track_upload, album_upload, artist_upload, playlist_upload

# --- MODIFIKASI DIMULAI (LOGIKA FALLBACK) ---
# 1. Definisikan Exception kustom
class QobuzContentUnavailableError(Exception):
    """Exception khusus yang dilempar saat konten tidak streamable/tersedia."""
    pass
# --- MODIFIKASI SELESAI ---


async def start_qobuz(url:str, user:dict):
    # --- MODIFIKASI DIMULAI (LOGIKA FALLBACK) ---
    
    clients_list = user.get('qobuz_clients_list', [])
    if not clients_list:
        return await edit_message(user['bot_msg'], "Kesalahan: Tidak ada daftar klien Qobuz yang ditemukan.")

    last_error = "Tidak ada error"
    
    # 2. Loop melalui setiap klien yang tersedia
    for i, client in enumerate(clients_list):
        # 3. Tetapkan klien saat ini untuk digunakan oleh fungsi downstream
        user['qobuz_api'] = client
        client_label = client.label or client.user_id # Gunakan label atau ID
        
        try:
            await edit_message(user['bot_msg'], f"Mencoba Akun #{i+1}/{len(clients_list)} ({client_label})...")

            # 4. Jalankan seluruh proses di dalam try...except
            items, item_id, type_dict, content = await check_type(url, user)
            
            if items:
                if type_dict['iterable_key'] == 'albums':
                    await start_artist(items, user, content)
                else:
                    await start_playlist(items, content, user)
            else:
                if type_dict["album"]:
                    await start_album(item_id, user)
                else:
                    await start_track(item_id, user, None)
            
            # 5. Jika berhasil, kirim pesan sukses dan keluar dari loop
            await edit_message(user['bot_msg'], f"Sukses mengunduh dengan Akun {client_label}!")
            return # Sukses!

        except QobuzContentUnavailableError as e:
            # 6. Konten tidak tersedia di klien ini, coba klien berikutnya
            last_error = f"Akun {client_label}: Konten tidak tersedia. ({e})"
            LOGGER.warning(last_error)
            continue # Lanjut ke iterasi loop berikutnya

        except Exception as e:
            # 7. Error fatal (misal disk penuh, error login, dll.), hentikan loop
            last_error = f"Error fatal di Akun {client_label}: {e}"
            LOGGER.error(f"{last_error}\n{traceback.format_exc()}")
            break # Keluar dari loop

    # 8. Jika loop selesai tanpa 'return', berarti semua klien gagal
    await edit_message(user['bot_msg'], f"Semua {len(clients_list)} akun Qobuz gagal.\nKesalahan terakhir: {last_error}")
    # --- MODIFIKASI SELESAI ---


async def start_album(item_id:int, user:dict, upload=True, basefolder=None):
    # Dapatkan klien saat ini dari kamus 'user'
    client = user['qobuz_api']
    
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err:
        # --- MODIFIKASI (LOGIKA FALLBACK) ---
        # Jika 'err' adalah 'UNAVAILABLE', lempar exception
        if err == "UNAVAILABLE":
            raise QobuzContentUnavailableError("Album tidak streamable.")
        # Jika tidak, kirim pesan error biasa
        return await send_message(user, err)
        # --- MODIFIKASI SELESAI ---
    
    # Get user quality by doing a track request
    track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)

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
    await run_concurrent_tasks(tasks, update_details)
    
    _, __, album_zip = fetch_zip_settings(user)
    
    if album_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        album_meta['folderpath'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_track(item_id:int, user:dict, track_meta:dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    # Dapatkan klien saat ini dari kamus 'user'
    client = user['qobuz_api']

    if not track_meta:
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err:
            # --- MODIFIKASI (LOGIKA FALLBACK) ---
            if err == "UNAVAILABLE":
                raise QobuzContentUnavailableError(f"Track {item_id} tidak streamable.")
            return await send_message(user, err)
            # --- MODIFIKASI SELESAI ---
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
    else:
        if track_meta['filepath'] == '' and basefolder is None:
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        else:
            filepath = basefolder
    
    # --- MODIFIKASI (LOGIKA FALLBACK) ---
    try:
        raw_data = await client.get_track_url(item_id, user)
        url = raw_data['url']
    except KeyError:
        # Lempar exception agar loop 'start_qobuz' bisa menangkapnya
        raise QobuzContentUnavailableError(f"Track {item_id} tidak memiliki URL (KeyError).")
    # --- MODIFIKASI SELESAI ---
        
    track_meta['extension'], track_meta['quality'] = await get_quality(raw_data, user)

    filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    filepath += f"/{filename}.{track_meta['extension']}"
    filepath = sanitize_filepath(filepath)
    track_meta['filepath'] = filepath

    err = await download_file(url, filepath)
    if err:
        return await send_message(user, err) # Error download (misal koneksi putus) adalah fatal
    
    await set_metadata(track_meta)

    if upload:
        await track_upload(track_meta, user, disable_link)
            
    return True


async def start_artist(albums, user, artist):
    artist_meta = await get_artist_meta(artist[0])
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{artist[0]['name']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath'])

    upload_album = True
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if bot_set.artist_zip:
        upload_album = False 

    for album in albums:
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        if bot_set.artist_zip:
            await edit_message(user['bot_msg'], lang.s.ZIPPING)
            artist_meta['folderpath'] = await zip_handler(artist_meta['folderpath'])
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)


async def start_playlist(tracks, playlist, user):
    # Dapatkan klien saat ini dari kamus 'user'
    client = user['qobuz_api']
    
    play_meta = await get_playlist_meta(playlist[0], tracks, user['r_id'], user)
    
    playlist_folder = None
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{play_meta['title']}"
        playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder
    
    # --- MODIFIKASI (LOGIKA FALLBACK) ---
    try:
        track_meta = await client.get_track_url(tracks[0]['id'], user)
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except KeyError:
        raise QobuzContentUnavailableError(f"Track pertama playlist {tracks[0]['id']} tidak memiliki URL.")
    # --- MODIFIKASI SELESAI ---

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': play_meta['title'],
        'type': play_meta['type']
    }

    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    upload = True
    playlist_zip, _, __ = fetch_zip_settings(user)
    
    if bot_set.playlist_conc:
        upload = False
        tasks = []
        for track in play_meta['tracks']:
            tasks.append(start_track(track['itemid'], user, track, upload, playlist_folder))
        await run_concurrent_tasks(tasks, update_details)
    else:
        i = 0
        if playlist_zip:
            upload = False
        for track in play_meta['tracks']:
            await progress_message(i, len(play_meta['tracks']), update_details)
            await start_track(track['itemid'], user, track, upload, playlist_folder, bot_set.disable_sort_link, True)
            i+=1

    if playlist_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        if playlist_sort:
            play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        play_meta['folderpath'] = await zip_handler(play_meta['folderpath'])
       
    if not upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
