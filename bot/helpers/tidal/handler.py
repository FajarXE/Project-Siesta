# [GANTI FILE: bot/helpers/tidal/handler.py]

import json
import base64
import random # <-- Dihapus
import os # <-- Ditambahkan

from pathvalidate import sanitize_filepath

# --- MODIFIKASI: Impor manajer ---
from .manager import tidal_manager
try:
    from .tidal_api import TidalApi
except ImportError:
    class TidalApi: pass
# --- MODIFIKASI SELESAI ---

from .utils import *
from .metadata import *

from ..utils import *
from ..metadata import set_metadata, get_audio_extension
from ..uploder import *
from ..message import send_message, edit_message # <-- Ditambahkan edit_message

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER
from config import Config


async def start_tidal(url:str, user:dict):
    # --- MODIFIKASI: HAPUS LOOP DARI SINI ---
    # Loop sekarang ada di download.py
    
    item_id, type_ = await parse_url(url)
    if not type_:
        # --- MODIFIKASI: Lempar error ---
        raise Exception("Invalid Tidal URL")
        # await send_message(user, "Invalid Tidal URL")
        # --- MODIFIKASI SELESAI ---

    # Asumsi 'tidal_api' sudah diinjeksi oleh download.py
    # Klien sudah ditetapkan oleh download.py
    
    if type_ == 'track':
        await start_track(item_id, user, None)
    elif type_ == 'artist':
        await start_artist(item_id, user)
    elif type_ == 'album':
        await start_album(item_id, user)
    elif type_ == 'playlist':
        # --- MODIFIKASI: Panggil start_playlist ---
        await start_playlist(item_id, user) 
        # --- MODIFIKASI SELESAI ---
        

async def start_track(track_id:int, user:dict, track_meta:dict | None,
    upload=True, basefolder=None, session=None, 
    quality=None, disable_link=False, disable_msg=False
  ):
    
    # --- MODIFIKASI: Dapatkan klien yang diinjeksi ---
    client: TidalApi = user['tidal_api']
    # --- MODIFIKASI SELESAI ---

    if not track_meta:
        try:
            # --- MODIFIKASI: Gunakan klien ---
            track_data = await client.get_track(track_id)
            # --- MODIFIKASI SELESAI ---
        except Exception as e:
            # --- MODIFIKASI: Lempar error ---
            raise e
            # return await send_message(user, e)
            # --- MODIFIKASI SELESAI ---

        track_meta = await get_track_metadata(track_id, track_data, user['r_id'])
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        # mostly session and quality will not be present
        session, quality = await get_stream_session(track_data, user)
    else:
        filepath = basefolder

    try:
        # --- MODIFIKASI: Gunakan klien ---
        stream_data = await client.get_stream_url(track_id, quality, session)
        # --- MODIFIKASI SELESAI ---
    except Exception as e:
        error = e
        # definitely region locked
        if 'Asset is not ready for playback' in str(e):
            error = f'Track [{track_id}] is not available in your region'
        LOGGER.error(error)
        # --- MODIFIKASI: Jangan kirim pesan, lempar error agar loop bisa menangani ---
        raise Exception(error)
        # return await send_message(user, error)
        # --- MODIFIKASI SELESAI ---
    

    if stream_data is not None:

        track_meta['quality'] = await get_quality(stream_data)

        if stream_data['manifestMimeType'] == 'application/dash+xml':
            manifest = base64.b64decode(stream_data['manifest'])
            urls, track_codec = parse_mpd(manifest)
        else:
            manifest = json.loads(base64.b64decode(stream_data['manifest']))
            track_codec = 'AAC' if 'mp4a' in manifest['codecs'] else manifest['codecs'].upper()
            urls = manifest['urls'][0]

        
        track_meta['folderpath'] = filepath
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        # not adding file extention now
        filepath += f"/{filename}"
        filepath = sanitize_filepath(filepath)
        track_meta['filepath'] = filepath


        if type(urls) == list:
            i = 0   # flawless
            temp_files = []
            for url in urls[0]:
                temp_path = f"{filepath}.{i}"
                err = await download_file(url, temp_path)
                if err:
                    # --- MODIFIKASI: Lempar error ---
                    raise Exception(err)
                    # return await send_message(user, err)
                    # --- MODIFIKASI SELESAI ---
                i+=1
                temp_files.append(temp_path)
            await merge_tracks(temp_files, filepath)
        else:
            err = await download_file(urls, filepath)
            if err:
                # --- MODIFIKASI: Lempar error ---
                raise Exception(err)
                # return await send_message(user, err)
                # --- MODIFIKASI SELESAI ---

        track_meta['extension'] = await get_audio_extension(filepath)
        
        if quality == 'HI_RES_LOSSLESS' and Config.TIDAL_CONVERT_M4A:
            await ffmpeg_convert(filepath)
            track_meta['filepath'] = track_meta['filepath'] + '.flac'
            os.remove(filepath)
        else:
            track_meta['filepath'] = track_meta['filepath'] + f".{track_meta['extension']}"
            # local filepath var is not updated so it contains old path before extention update
            os.rename(filepath, track_meta['filepath'])

        await set_metadata(track_meta)

        if upload:
            await track_upload(track_meta, user, False)

    return True


async def start_album(album_id:int, user:dict, upload=True, basefolder=None):
    # --- MODIFIKASI: Dapatkan klien yang diinjeksi ---
    client: TidalApi = user['tidal_api']
    # --- MODIFIKASI SELESAI ---
    
    try:
        # --- MODIFIKASI: Gunakan klien ---
        album_data = await client.get_album(album_id)
        # --- MODIFIKASI SELESAI ---
    except Exception as e:
        # --- MODIFIKASI: Lempar error ---
        raise e
        # return await send_message(user, e)
        # --- MODIFIKASI SELESAI ---
        
    # --- MODIFIKASI: Gunakan klien ---
    tracks_data = await client.get_album_tracks(album_id)
    # --- MODIFIKASI SELESAI ---
    
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'])

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder # Path direktori asli (string)

    # get a track to get quality
    track_id = tracks_data['items'][0]['id']
    # --- MODIFIKASI: Gunakan klien ---
    track_data = await client.get_track(track_id)
    session, quality = await get_stream_session(track_data, user)
    stream_data = await client.get_stream_url(track_id, quality, session)
    # --- MODIFIKASI SELESAI ---

    album_meta['quality'] = await get_quality(stream_data)

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # concurrent
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder, session, quality))

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
        # --- PERBAIKAN: Simpan path zip di key baru, jangan timpa folderpath ---
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    # Upload
    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        # album_upload akan memeriksa 'zip_path' dan 'folderpath'
        # dan memanggil cleanup yang akan menggunakan 'folderpath' asli
        await album_upload(album_meta, user)


# --- TAMBAHAN BARU UNTUK PLAYLIST ---
async def start_playlist(playlist_id:str, user:dict, upload=True, basefolder=None):
    # --- MODIFIKASI: Dapatkan klien yang diinjeksi ---
    client: TidalApi = user['tidal_api']
    # --- MODIFIKASI SELESAI ---
    
    try:
        # --- MODIFIKASI: Gunakan klien untuk get_playlist ---
        playlist_data = await client.get_playlist(playlist_id)
        # --- MODIFIKASI SELESAI ---
    except Exception as e:
        # --- MODIFIKASI: Lempar error ---
        raise e
        # --- MODIFIKASI SELESAI ---
        
    # --- MODIFIKASI: Gunakan klien untuk get_playlist_tracks dengan PAGINATION ---
    total_tracks = playlist_data.get('numberOfTracks', 0)
    if total_tracks == 0:
        LOGGER.warning(f"Playlist {playlist_id} terdaftar sebagai kosong (0 tracks).")
        
    tracks_data = await client.get_playlist_tracks(playlist_id, total_tracks)
    # --- MODIFIKASI SELESAI ---
    
    # --- MODIFIKASI: Gunakan get_playlist_metadata ---
    playlist_meta = await get_playlist_metadata(playlist_id, playlist_data, tracks_data, user['r_id'])
    # --- MODIFIKASI SELESAI ---

    # Cek jika playlist kosong
    if not playlist_meta['tracks']:
        LOGGER.warning(f"Playlist {playlist_id} kosong atau tidak berisi track.")
        raise Exception("Playlist ini kosong atau tidak berisi track yang valid.")

    # Gunakan 'artist' dari metadata (creator) untuk path
    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{playlist_meta['provider']}/{playlist_meta['artist']}/{playlist_meta['title']}"
    
    playlist_folder = sanitize_filepath(playlist_folder)
    playlist_meta['folderpath'] = playlist_folder # Path direktori asli (string)

    # get a track to get quality
    first_track_raw = None
    for item in tracks_data['items']:
        if item.get('type') == 'track' and item.get('item'):
            first_track_raw = item['item']
            break
    
    if not first_track_raw:
        raise Exception("Playlist tidak berisi track valid untuk menentukan kualitas.")

    session, quality = await get_stream_session(first_track_raw, user)
    stream_data = await client.get_stream_url(first_track_raw['id'], quality, session)
    # --- MODIFIKASI SELESAI ---

    playlist_meta['quality'] = await get_quality(stream_data)

    if upload:
        playlist_meta['poster_msg'] = await post_art_poster(user, playlist_meta)

    # concurrent
    tasks = []
    for track in playlist_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder, session, quality))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': playlist_meta['title'],
        'type': playlist_meta['type']
    }
    await run_concurrent_tasks(tasks, update_details)
    
    _, __, album_zip = fetch_zip_settings(user) # Gunakan pengaturan zip album untuk playlist
    if album_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        # --- PERBAIKAN: Simpan path zip di key baru, jangan timpa folderpath ---
        playlist_meta['zip_path'] = await zip_handler(playlist_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    # Upload
    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        # album_upload akan memeriksa 'zip_path' dan 'folderpath'
        await album_upload(playlist_meta, user)
# --- AKHIR TAMBAHAN ---


async def start_artist(artist_id:int, user:dict):
    # --- MODIFIKASI: Dapatkan klien yang diinjeksi ---
    client: TidalApi = user['tidal_api']
    # --- MODIFIKASI SELESAI ---

    # --- MODIFIKASI: Gunakan klien ---
    artist_data = await client.get_artist(artist_id)
    artist_meta = await get_artist_metadata(artist_data, user['r_id'])
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath']) # Path direktori asli (string)
    
    try:
        artist_albums = await client.get_artist_albums(artist_id)
        artist_eps = await client.get_artist_albums_ep_singles(artist_id)
    except Exception as e:
        # --- MODIFIKASI: Lempar error ---
        raise e
        # return await send_message(user, e)
        # --- MODIFIKASI SELESAI ---

    # --- MODIFIKASI: Teruskan 'user' ke sort_album_from_artist ---
    albums = await sort_album_from_artist(artist_albums['items'], user)
    ep_singles = await sort_album_from_artist(artist_eps['items'], user)
    # --- MODIFIKASI SELESAI ---
    
    albums.extend(ep_singles)

    upload_album = True
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if bot_set.artist_zip:
        upload_album = False # final decision

    for album in albums:
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        if bot_set.artist_zip:
            await edit_message(user['bot_msg'], lang.s.ZIPPING)
            # --- PERBAIKAN: Simpan path zip di key baru, jangan timpa folderpath ---
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
            # --- AKHIR PERBAIKAN ---
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        # Asumsi artist_upload juga memeriksa 'zip_path' dan memanggil cleanup
        await artist_upload(artist_meta, user)
