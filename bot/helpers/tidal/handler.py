# [GANTI FILE: bot/helpers/tidal/handler.py]

import json
import base64
import os
import asyncio 
from datetime import datetime 

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
from .mqa_identifier import MqaIdentifier 

from ..utils import *
from ..metadata import set_metadata, get_audio_extension
from ..uploder import *
from ..message import send_message, edit_message 

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER
from config import Config


async def start_tidal(url:str, user:dict):
    item_id, type_ = await parse_url(url)
    if not type_:
        raise Exception("Invalid Tidal URL")

    if type_ == 'track':
        await start_track(item_id, user, None)
    elif type_ == 'artist':
        await start_artist(item_id, user)
    elif type_ == 'album':
        await start_album(item_id, user)
    elif type_ == 'playlist':
        await start_playlist(item_id, user) 
        

async def start_track(track_id:int, user:dict, track_meta:dict | None,
    upload=True, basefolder=None, session=None, 
    quality=None, disable_link=False, disable_msg=False
  ):
    
    # --- MODIFIKASI: Dapatkan klien yang diinjeksi ---
    client: TidalApi = user['tidal_api']
    # --- MODIFIKASI SELESAI ---

    # --- MODIFIKASI BESAR: Logika Pengambilan Metadata ---
    # Jika track_meta tidak ada, ATAU 'copyright' tidak ada (menandakan ini adalah stub)
    # maka kita HARUS mengambil metadata lengkap.
    if not track_meta or 'copyright' not in track_meta:
        try:
            # 1. Ambil data track LENGKAP
            track_data = await client.get_track(track_id)
        except Exception as e:
            raise e # Lempar error jika trek tidak ditemukan

        # 2. Ambil cover/thumb dari stub jika ada (diteruskan dari album/playlist)
        cover = track_meta.get('cover') if track_meta else None
        thumbnail = track_meta.get('thumbnail') if track_meta else None
        
        # 3. Buat metadata LENGKAP menggunakan data LENGKAP
        track_meta_full = await get_track_metadata(track_id, track_data, user['r_id'], cover, thumbnail)
        
        # 4. Jika kita di dalam album/playlist, 'basefolder' sudah diatur.
        if basefolder:
            filepath = basefolder
        else:
            # Jika ini trek tunggal, bangun path dari metadata LENGKAP
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta_full['provider']}/{track_meta_full['albumartist']}/{track_meta_full['album']}"
        
        # 5. Dapatkan session dan quality (penting untuk download)
        session, quality = await get_stream_session(track_data, user)
        
        # 6. Ganti track_meta yang tidak lengkap dengan yang lengkap
        # Kita perlu mempertahankan info path/nama file dari stub
        # (seperti judul album kustom dari playlist)
        if track_meta:
            # Pertahankan path dari stub
            track_meta_full['album'] = track_meta['album']
            track_meta_full['albumartist'] = track_meta['albumartist']
            track_meta_full['artist'] = track_meta['artist']
            track_meta_full['title'] = track_meta['title']
            track_meta_full['tracknumber'] = track_meta['tracknumber']
        
        track_meta = track_meta_full

    else:
        # track_meta sudah lengkap (misalnya, dari panggilan start_track tunggal sebelumnya)
        filepath = basefolder
    # --- AKHIR MODIFIKASI BESAR ---


    try:
        # --- MODIFIKASI: Gunakan klien ---
        stream_data = await client.get_stream_url(track_id, quality, session)
        # --- MODIFIKASI SELESAI ---
    except Exception as e:
        error = e
        if 'Asset is not ready for playback' in str(e):
            error = f'Track [{track_id}] is not available in your region'
        LOGGER.error(error)
        raise Exception(error)
    

    if stream_data is not None:

        track_meta['quality'] = await get_quality(stream_data)

        if stream_data['manifestMimeType'] == 'application/dash+xml':
            manifest = base64.b64decode(stream_data['manifest'])
            urls, track_codec = parse_mpd(manifest)
        else:
            manifest = json.loads(base64.b64decode(stream_data['manifest']))
            track_codec = 'AAC' if 'mp4a' in manifest['codecs'] else manifest['codecs'].upper()
            urls = manifest['urls'][0]

        
        # --- TAMBAHAN BARU: Simpan info codec awal ---
        # Kita harus memasukkan ini ke dalam track_meta LENGKAP
        track_meta['codec'] = track_codec
        if stream_data['audioQuality'] == 'HI_RES_LOSSLESS':
            track_meta['bit_depth'] = 24
        else:
            track_meta['bit_depth'] = 16
            
        if track_codec in {'EAC3', 'MHA1', 'AC4'}:
            track_meta['sample_rate'] = 48
        else:
            track_meta['sample_rate'] = 44.1
        # --- AKHIR TAMBAHAN ---
        
        track_meta['folderpath'] = filepath
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
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
                    raise Exception(err)
                i+=1
                temp_files.append(temp_path)
            await merge_tracks(temp_files, filepath)
        else:
            err = await download_file(urls, filepath)
            if err:
                raise Exception(err)

        track_meta['extension'] = await get_audio_extension(filepath)
        
        
        # --- MODIFIKASI: Ambil SEMUA pengaturan pengguna ---
        try:
            _, __, user_mqa_fix, user_convert_m4a = tidal_manager.get_user_quality_settings(user['user_id'])
        except Exception:
            user_mqa_fix = "ON" # Fallback
            user_convert_m4a = "OFF" # Fallback
        # --- AKHIR MODIFIKASI ---
        

        # --- MODIFIKASI: Gunakan 'user_convert_m4a' ---
        if quality == 'HI_RES_LOSSLESS' and user_convert_m4a == "ON":
            LOGGER.info(f"Mengonversi M4A ke FLAC untuk user {user['user_id']} Sesuai pengaturan.")
            await ffmpeg_convert(filepath)
            track_meta['filepath'] = track_meta['filepath'] + '.flac'
            os.remove(filepath)
        else:
            if quality == 'HI_RES_LOSSLESS' and user_convert_m4a == "OFF":
                LOGGER.info(f"Melewatkan konversi M4A untuk user {user['user_id']} Sesuai pengaturan.")
            track_meta['filepath'] = track_meta['filepath'] + f".{track_meta['extension']}"
            os.rename(filepath, track_meta['filepath'])
        # --- AKHIR MODIFIKASI ---
            
            
        # --- MODIFIKASI: Analisis MQA dengan Pengecekan Pengguna ---
        track_meta['mqa_details'] = None # Inisialisasi
        
        if track_meta['codec'] == 'MQA' and user_mqa_fix == "ON":
            try:
                LOGGER.info(f"Menganalisis file MQA: {track_meta['filepath']} (User: {user['user_id']})")
                mqa_file = await asyncio.to_thread(MqaIdentifier, track_meta['filepath'])
                
                if mqa_file.is_mqa:
                    LOGGER.info(f"MQA terdeteksi: {mqa_file.get_original_sample_rate()}kHz (Studio: {mqa_file.is_mqa_studio})")
                    track_meta['mqa_details'] = mqa_file
                    track_meta['bit_depth'] = mqa_file.bit_depth
                    track_meta['sample_rate'] = mqa_file.get_original_sample_rate()
                else:
                    LOGGER.warning("Codec adalah MQA, tetapi sinkronisasi MQA tidak ditemukan.")
            except Exception as e:
                LOGGER.warning(f"Gagal memproses MQA: {e}")
        elif track_meta['codec'] == 'MQA' and user_mqa_fix == "OFF":
             LOGGER.info(f"Melewatkan analisis MQA untuk user {user['user_id']} sesuai pengaturan.")
        # --- AKHIR MODIFIKASI ---

        await set_metadata(track_meta) # Sekarang dipanggil dengan track_meta LENGKAP

        if upload:
            await track_upload(track_meta, user, False)

    return True


# --- MODIFIKASI: start_album (Sangat Disederhanakan) ---
async def start_album(album_id:int, user:dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    try:
        album_data = await client.get_album(album_id)
        tracks_data = await client.get_album_tracks(album_id)
    except Exception as e:
        raise e
        
    # Panggil get_album_metadata (yang sekarang membuat stub)
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'])

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    # --- PERBAIKAN: Ambil session/quality di sini ---
    # Kita tidak bisa lagi mengambilnya dari start_track karena loop
    try:
        track_id_sample = tracks_data['items'][0]['id']
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        album_meta['quality'] = await get_quality(stream_data)
    except Exception as e:
        LOGGER.error(f"Gagal mendapatkan info kualitas untuk album {album_id}: {e}")
        # Tetapkan fallback agar unduhan tetap berjalan
        session, quality = (None, "LOSSLESS") 
        album_meta['quality'] = "LOSSLESS"
    # --- AKHIR PERBAIKAN ---

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # concurrent
    tasks = []
    # 'track' di sini sekarang adalah "stub" dari get_album_metadata
    for track in album_meta['tracks']:
        # Panggil start_track dengan stub. 
        # start_track akan mendeteksi stub dan mengambil metadata lengkap.
        tasks.append(start_track(
            track['itemid'], 
            user, 
            track, # Ini adalah stub-nya
            False, 
            album_folder, 
            session, # Teruskan session/quality yang sudah kita dapatkan
            quality
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    await run_concurrent_tasks(tasks, update_details)
    
    _, album_zip, __ = fetch_zip_settings(user)
    if album_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    # Upload
    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
# --- AKHIR MODIFIKASI ---


# --- MODIFIKASI: start_playlist (Sangat Disederhanakan) ---
async def start_playlist(playlist_id:str, user:dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    try:
        playlist_data = await client.get_playlist(playlist_id)
    except Exception as e:
        raise e
        
    total_tracks = playlist_data.get('numberOfTracks', 0)
    if total_tracks == 0:
        LOGGER.warning(f"Playlist {playlist_id} terdaftar sebagai kosong (0 tracks).")
        
    tracks_data = await client.get_playlist_tracks(playlist_id, total_tracks)
    
    # Panggil get_playlist_metadata (yang sekarang membuat stub)
    playlist_meta = await get_playlist_metadata(playlist_id, playlist_data, tracks_data, user['r_id'])

    if not playlist_meta['tracks']:
        LOGGER.warning(f"Playlist {playlist_id} kosong atau tidak berisi track.")
        raise Exception("Playlist ini kosong atau tidak berisi track yang valid.")

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{playlist_meta['provider']}/{playlist_meta['artist']}/{playlist_meta['title']}"
    
    playlist_folder = sanitize_filepath(playlist_folder)
    playlist_meta['folderpath'] = playlist_folder 

    # --- PERBAIKAN: Ambil session/quality di sini ---
    try:
        # 'track' di sini adalah stub, jadi kita pakai itemid
        track_id_sample = playlist_meta['tracks'][0]['itemid'] 
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        playlist_meta['quality'] = await get_quality(stream_data)
    except Exception as e:
        LOGGER.error(f"Gagal mendapatkan info kualitas untuk playlist {playlist_id}: {e}")
        session, quality = (None, "LOSSLESS")
        playlist_meta['quality'] = "LOSSLESS"
    # --- AKHIR PERBAIKAN ---

    if upload:
        playlist_meta['poster_msg'] = await post_art_poster(user, playlist_meta)

    # concurrent
    tasks = []
    # 'track' di sini sekarang adalah "stub" dari get_playlist_metadata
    for track in playlist_meta['tracks']:
        # Panggil start_track dengan stub. 
        tasks.append(start_track(
            track['itemid'], 
            user, 
            track, # Ini adalah stub-nya
            False, 
            playlist_folder, 
            session, # Teruskan session/quality yang sudah kita dapatkan
            quality
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': playlist_meta['title'],
        'type': playlist_meta['type']
    }
    await run_concurrent_tasks(tasks, update_details)
    
    playlist_zip, _, __ = fetch_zip_settings(user)

    if playlist_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        playlist_meta['zip_path'] = await zip_handler(playlist_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(playlist_meta, user)
# --- AKHIR MODIFIKASI ---


async def start_artist(artist_id:int, user:dict):
    client: TidalApi = user['tidal_api']

    artist_data = await client.get_artist(artist_id)
    artist_meta = await get_artist_metadata(artist_data, user['r_id'])
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath']) 
    
    try:
        artist_albums = await client.get_artist_albums(artist_id)
        artist_eps = await client.get_artist_albums_ep_singles(artist_id)
    except Exception as e:
        raise e

    albums = await sort_album_from_artist(artist_albums['items'], user)
    ep_singles = await sort_album_from_artist(artist_eps['items'], user)
    
    albums.extend(ep_singles)

    upload_album = True
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if bot_set.artist_zip:
        upload_album = False # final decision

    for album in albums:
        # Panggil start_album. start_album sekarang akan menangani 
        # pengambilan metadata trek lengkap secara internal.
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        _, __, artist_zip = fetch_zip_settings(user)
        if artist_zip: 
            await edit_message(user['bot_msg'], lang.s.ZIPPING)
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)
