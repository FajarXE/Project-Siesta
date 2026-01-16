# [GANTI FILE: bot/helpers/qobuz/handler.py]

import shutil
import os
from .utils import *
from config import Config

from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata
from ..message import edit_message
from bot.logger import LOGGER
import traceback

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
    """
    Memaksa penulisan tag kustom (creation_time, RELEASETIME, ORIGINALDATE)
    menggunakan Mutagen, membypass filter set_metadata standar.
    """
    if not os.path.exists(filepath):
        return

    ext = filepath.split('.')[-1].lower()
    
    # Tag spesifik yang diminta user
    target_keys = ['creation_time', 'RELEASETIME', 'ORIGINALDATE']
    tags_to_write = {}
    
    for k in target_keys:
        val = metadata.get(k)
        if val:
            tags_to_write[k] = str(val)
            
    if not tags_to_write:
        return

    try:
        if ext == 'flac':
            if FLAC:
                try:
                    audio = FLAC(filepath)
                    for k, v in tags_to_write.items():
                        # Untuk FLAC, kita tulis sebagai Vorbis Comments
                        # Kita pertahankan casing sesuai request (huruf kecil/besar)
                        audio[k] = v
                    audio.save()
                    LOGGER.info(f"Custom tags FLAC berhasil ditulis: {tags_to_write}")
                except Exception as e:
                    LOGGER.warning(f"Error menulis tag FLAC: {e}")
            else:
                LOGGER.warning("Module mutagen.flac tidak ditemukan.")
                
        elif ext == 'mp3':
            if ID3:
                try:
                    try:
                        audio = ID3(filepath)
                    except:
                        audio = ID3()
                        audio.save(filepath)
                    
                    for k, v in tags_to_write.items():
                        # Untuk MP3, gunakan TXXX frame (User Defined Text)
                        audio.add(TXXX(encoding=3, desc=k, text=v))
                    audio.save()
                    LOGGER.info(f"Custom tags MP3 berhasil ditulis: {tags_to_write}")
                except Exception as e:
                    LOGGER.warning(f"Error menulis tag MP3: {e}")
            else:
                 LOGGER.warning("Module mutagen.id3 tidak ditemukan.")

    except Exception as e:
        LOGGER.warning(f"Gagal umum dalam force_custom_tags: {e}")


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

            if items is not None:
                if not items:
                    artist_name = "N/A"
                    if content and isinstance(content, list) and len(content) > 0:
                        artist_name = content[0].get('name', item_id)
                    
                    await edit_message(user['bot_msg'], f"Sukses, tapi artis/playlist '{artist_name}' tidak memiliki item (album/trek) untuk diunduh.")
                    return 

                if type_dict['iterable_key'] == 'albums':
                    await start_artist(items, user, content)
                else:
                    await start_playlist(items, content, user)
            else:
                # Jika items adalah None, berarti itu adalah Album atau Track tunggal
                if type_dict.get("album") is True:
                    await start_album(item_id, user)
                elif type_dict.get("album") is False:
                    await start_track(item_id, user, None)
                else:
                    raise Exception(f"Tipe konten tidak diketahui (items=None, tapi type_dict aneh): {type_dict}")
            
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
            break 

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

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            cover_dest = os.path.join(album_meta['folderpath'], "cover.jpg")
            if not os.path.exists(cover_dest):
                shutil.copy2(album_meta['cover'], cover_dest)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover.jpg ke folder album: {e}")

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

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
        await set_metadata(track_meta, user['user_id'])
        
        # --- PAKSA TULIS TAG CUSTOM (Fix untuk creation_time, RELEASETIME, dll) ---
        await force_custom_tags(full_path, track_meta)
        # --------------------------------------------------------------------------

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
    
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: 
        upload_album = False 

    for album in albums:
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        if artist_zip: 
            await edit_message(user['bot_msg'], f"Menyiapkan folder artis {artist_meta['title']} menjadi .zip...")
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
        
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
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
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

    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try:
            cover_dest = os.path.join(play_meta['folderpath'], "cover.jpg")
            if not os.path.exists(cover_dest):
                shutil.copy2(play_meta['cover'], cover_dest)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover.jpg ke folder playlist: {e}")

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {play_meta['totaltracks']} lagu menjadi .zip...")
        if playlist_sort:
            play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
       
    if not upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
