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

from bot.settings import bot_set 

from ..uploder import track_upload, album_upload, artist_upload, playlist_upload

try:
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TXXX
except ImportError:
    FLAC = None
    ID3 = None
    LOGGER.warning("Mutagen tidak terinstall. Custom tags mungkin tidak tersimpan.")

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
    
    for i, client in enumerate(clients_list):
        user['qobuz_api'] = client
        client_label = client.label or client.user_id 
        try:
            await edit_message(user['bot_msg'], f"Mencoba Akun #{i+1}/{len(clients_list)} ({client_label})...")
            
            items, item_id, type_dict, content = await check_type(url, user)
            
            if items is None and item_id is None:
                 raise QobuzContentUnavailableError("Gagal mendapatkan item/ID valid.")

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
            
            await edit_message(user['bot_msg'], f"Selesai memproses dengan Akun {client_label}.")
            return 

        except QobuzContentUnavailableError as e:
            last_error = f"{e}"
            LOGGER.warning(f"Akun {client_label} gagal mengambil metadata: {e}")
            continue 
        except Exception as e:
            last_error = f"{e}"
            LOGGER.error(f"Fatal Error Qobuz (Start): {e}\n{traceback.format_exc()}")
            break 

    try: await edit_message(user['bot_msg'], f"Gagal: {last_error}")
    except: pass

async def start_album(item_id:int, user:dict, upload=True, basefolder=None):
    client = user['qobuz_api']
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err: return await send_message(user, err)
    
    # Coba ambil sampel track (bisa error jika region lock)
    try: track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)
    except: 
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
    
    # Booklet
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

# =======================================================================
#  [UPDATE] START TRACK DENGAN MULTI-ACCOUNT RETRY
# =======================================================================
async def start_track(item_id:int, user:dict, track_meta:dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    # Simpan client utama (yang sedang dipakai playlist)
    primary_client = user.get('qobuz_api')
    
    # Siapkan daftar semua client untuk fallback
    all_clients = user.get('qobuz_clients_list', [])
    if not all_clients and primary_client:
        all_clients = [primary_client]

    if not track_meta:
        # Jika track_meta kosong, coba ambil pakai client utama dulu
        # Jika gagal di sini, mungkin memang error metadata (bukan URL)
        client = primary_client
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err: return await send_message(user, err)
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)
    else: 
        filepath = basefolder
    
    # --- LOGIKA RETRY MENCARI URL ---
    raw_data = None
    url = None
    last_error = None
    
    # Urutan: Coba client utama dulu -> lalu sisanya
    client_queue = [primary_client] + [c for c in all_clients if c != primary_client]
    
    for client in client_queue:
        if not client: continue
        try:
            # Coba ambil URL dengan client ini
            temp_data = await client.get_track_url(item_id, user)
            if temp_data and temp_data.get('url'):
                raw_data = temp_data
                url = raw_data['url']
                # Jika kita berhasil pakai akun cadangan, log infonya
                if client != primary_client:
                    LOGGER.info(f"Track {item_id}: Berhasil diambil dari akun alternatif {client.label or client.user_id}")
                break # Sukses, keluar dari loop
        except Exception as e:
            last_error = e
            # Lanjut ke akun berikutnya
            continue 

    # Jika setelah semua akun dicoba masih gagal
    if not url:
        LOGGER.warning(f"Gagal mendapatkan URL Track ID {item_id} di {len(client_queue)} akun. Error: {last_error}. Skipping...")
        return False # Baru return False di sini
        
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
        LOGGER.error(f"Error processing track {item_id} (Download/Tag): {e}")
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
    
    try:
        track_meta = await client.get_track_url(tracks[0]['id'], user)
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except:
        play_meta['quality'] = "Unknown"

    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': play_meta['title'], 'type': play_meta['type']}
    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    upload = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    user_id = user.get('user_id')
    raw_user_data = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
    user_mode = raw_user_data.get('upload_mode', 'Telegram')
    
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        upload = False
        LOGGER.info(f"Mode Cloud ({user_mode}) terdeteksi. Mematikan upload per-track.")

    if bot_set.playlist_conc:
        upload = False 
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
            success = await start_track(track['itemid'], user, track, upload, playlist_folder, bot_set.disable_sort_link, True)
            if success: 
                successful_tracks_non_conc.append(track)
            i+=1
        play_meta['tracks'] = successful_tracks_non_conc
        play_meta['totaltracks'] = len(successful_tracks_non_conc)

    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try: shutil.copy2(play_meta['cover'], os.path.join(play_meta['folderpath'], "cover.jpg"))
        except: pass

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Zipping {play_meta['totaltracks']} tracks...")
        if playlist_sort: play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])
       
    if not upload:
        if not play_meta['tracks']:
            await edit_message(user['bot_msg'], "Gagal: Tidak ada lagu yang berhasil diunduh.")
            return
            
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(play_meta, user)
