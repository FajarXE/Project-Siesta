import os
import asyncio
import logging
from pyrogram.errors import MessageNotModified

# Import internal bot modules
from config import Config
from bot.helpers.utils import format_string, create_simple_text, post_art_poster
from bot.helpers.message import edit_message, send_message
from bot.helpers.uploder import track_upload, album_upload, playlist_upload, artist_upload
from bot.helpers.metadata import set_metadata, create_cover_file 
from bot.helpers.spotify.manager import spotify_manager
import bot.helpers.translations as lang

LOGGER = logging.getLogger("SpotifyHandler")

async def start_spotify(link: str, user: dict):
    client = spotify_manager.get_client()
    if not client:
        await spotify_manager.initialize_clients()
        client = spotify_manager.get_client()
        if not client:
            await send_message(user, "❌ **Spotify Gagal:** Bot belum login.", 'text')
            return

    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Menganalisis Link...")
    
    parsed_data = client.parse_url(link)
    if not parsed_data:
        await edit_message(msg, "❌ Link Spotify tidak valid.")
        return

    item_type_enum, item_id = parsed_data
    item_type = item_type_enum.name.lower() if hasattr(item_type_enum, 'name') else str(item_type_enum).lower()

    LOGGER.info(f"Spotify Processing: Type={item_type}, ID={item_id}")

    try:
        if item_type == 'track':
            await process_track(client, item_id, user)
        elif item_type == 'album':
            await process_album(client, item_id, user)
        elif item_type == 'playlist':
            await process_playlist(client, item_id, user)
        elif item_type == 'artist':
            await process_artist(client, item_id, user)
        elif item_type == 'episode':
            await process_track(client, item_id, user, is_episode=True)
        else:
            await edit_message(msg, f"❌ Tipe konten '{item_type}' belum didukung.")
            
    except Exception as e:
        LOGGER.error(f"Spotify Handler Error: {e}", exc_info=True)
        await edit_message(msg, f"❌ **Error:** {str(e)}")


async def process_track(client, track_id, user, is_episode=False):
    msg = user.get('bot_msg')
    await edit_message(msg, f"⬇️ **Spotify:** Mengunduh {'Episode' if is_episode else 'Lagu'}...")

    try:
        if is_episode:
             track_info = client.get_episode_info(track_id, "HIGH", None)
        else:
             track_info = client.get_track_info(track_id, "HIGH", None)
             
        if not track_info:
            raise Exception("Gagal mengambil metadata.")

        download_result = None
        if is_episode:
             download_result = client.get_episode_download(track_id=track_id, quality_tier="HIGH")
        else:
             download_result = client.get_track_download(track_id=track_id, quality_tier="HIGH")

        if not download_result or not download_result.temp_file_path:
            raise Exception("Gagal mengunduh stream audio.")

        meta = map_spotify_to_bot_metadata(track_info, user, is_episode)
        
        final_filename = f"{meta['artist']} - {meta['title']}.ogg".replace("/", "_")
        user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify"
        os.makedirs(user_folder, exist_ok=True)
        
        final_path = os.path.join(user_folder, final_filename)
        import shutil
        shutil.move(download_result.temp_file_path, final_path)
        
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder

        # Thumb
        if meta.get('cover'):
            thumb_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
            meta['thumb'] = thumb_path
            
        await edit_message(msg, "🏷 **Spotify:** Menulis Metadata...")
        await set_metadata(meta, user['user_id'])

        await edit_message(msg, "⬆️ **Spotify:** Mengunggah...")
        await track_upload(meta, user)

    except Exception as e:
        raise e


async def process_album(client, album_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Album...")

    album_info = client.get_album_info(album_id)
    if not album_info:
        raise Exception("Album tidak ditemukan.")

    tracks = album_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Album ditemukan: {album_info.name}\nJumlah Lagu: {total}")
    
    # [FIX ZIP 1] Siapkan Metadata Album LENGKAP untuk Poster & ZIP
    meta_album = {
        'title': album_info.name,
        'artist': album_info.artist,
        'cover': album_info.all_track_cover_jpg_url,
        'type': 'album',
        'provider': 'Spotify',
        'date': str(album_info.release_year),
        'release_date': str(album_info.release_year),
        'quality': "High (320kbps)",
        
        # [FIX METADATA KOSONG] Isi Total Tracks & Volumes
        'totaltracks': str(total),
        'totalvolumes': "1", # Default 1
        'explicit': "False", # Default album
        
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if meta_album.get('cover'):
         poster_path = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
         meta_album['thumb'] = poster_path

    # Kirim Poster dengan Metadata yang sudah diisi
    user['poster_msg'] = await post_art_poster(user, meta_album)

    processed_tracks = []
    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify/{album_info.name}"
    os.makedirs(user_folder, exist_ok=True)

    for i, track in enumerate(tracks):
        try:
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Album:** ({current_num}/{total})\n`{track.name}`")
            
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                meta = map_spotify_to_bot_metadata(track, user)
                
                # Update total tracks di meta individu juga
                meta['totaltracks'] = str(total)
                
                clean_title = meta['title'].replace("/", "_")
                filename = f"{str(meta['tracknumber']).zfill(2)}. {clean_title}.ogg"
                final_path = os.path.join(user_folder, filename)
                
                import shutil
                shutil.move(download_result.temp_file_path, final_path)
                
                meta['filepath'] = final_path
                meta['folderpath'] = user_folder
                
                meta['cover'] = album_info.all_track_cover_jpg_url
                if meta_album.get('thumb'):
                    meta['thumb'] = meta_album['thumb']
                else:
                    t_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
                    meta['thumb'] = t_path
                
                await set_metadata(meta, user['user_id'])
                processed_tracks.append(meta)
                
        except Exception as e:
            LOGGER.error(f"Gagal download track {track.name}: {e}")
            continue

    if not processed_tracks:
        raise Exception("Gagal mengunduh semua lagu dalam album.")

    # [FIX ZIP 2] Masukkan tracks yang sudah diproses ke meta_album
    meta_album['tracks'] = processed_tracks
    meta_album['folderpath'] = user_folder
    
    # Panggil Album Upload (Uploader akan cek setting user utk ZIP)
    await album_upload(meta_album, user)


async def process_playlist(client, playlist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Playlist...")

    playlist_info = client.get_playlist_info(playlist_id)
    if not playlist_info:
        raise Exception("Playlist tidak ditemukan / Privat.")

    tracks = playlist_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Playlist: {playlist_info.name}\nTotal: {total} Lagu")

    meta_playlist = {
        'title': playlist_info.name,
        'artist': playlist_info.creator,
        'cover': playlist_info.cover_url,
        'type': 'playlist',
        'provider': 'Spotify',
        'totaltracks': str(total), # Isi metadata
        'totalvolumes': "1",
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if meta_playlist.get('cover'):
         p_path = await create_cover_file(meta_playlist['cover'], meta_playlist, thumbnail=False)
         meta_playlist['thumb'] = p_path
         
    user['poster_msg'] = await post_art_poster(user, meta_playlist)

    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify/{playlist_info.name}"
    os.makedirs(user_folder, exist_ok=True)

    processed_tracks = []

    for i, track in enumerate(tracks):
        try:
            if not track or not track.id: continue
            
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Playlist:** ({current_num}/{total})\n`{track.name}`")
            
            is_episode = False
            if hasattr(track, 'download_extra_kwargs'):
                 kwargs = getattr(track, 'download_extra_kwargs', {})
                 if isinstance(kwargs, dict) and kwargs.get('is_episode'):
                      is_episode = True

            if is_episode:
                 dl_res = client.get_episode_download(track_id=track.id, quality_tier="HIGH")
            else:
                 dl_res = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if dl_res and dl_res.temp_file_path:
                meta = map_spotify_to_bot_metadata(track, user, is_episode)
                
                clean_artist = meta['artist'].replace("/", "_")
                clean_title = meta['title'].replace("/", "_")
                filename = f"{clean_artist} - {clean_title}.ogg"
                
                final_path = os.path.join(user_folder, filename)
                import shutil
                shutil.move(dl_res.temp_file_path, final_path)
                
                meta['filepath'] = final_path
                meta['folderpath'] = user_folder
                
                if meta.get('cover'):
                    t_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
                    meta['thumb'] = t_path
                
                await set_metadata(meta, user['user_id'])
                processed_tracks.append(meta)

        except Exception as e:
            LOGGER.error(f"Skip track playlist: {e}")
            continue

    if not processed_tracks:
        raise Exception("Gagal mengunduh isi playlist.")

    meta_playlist['tracks'] = processed_tracks
    meta_playlist['folderpath'] = user_folder
    meta_playlist['quality'] = "High (320kbps)"
    
    await playlist_upload(meta_playlist, user)


async def process_artist(client, artist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "⚠️ **Info:** Download Artis belum didukung penuh. Silakan download per Album.")


# --- HELPER MAPPING (METADATA FIX) ---
def map_spotify_to_bot_metadata(track_info, user, is_episode=False):
    """
    Mengubah Objek TrackInfo menjadi Dictionary Metadata Bot.
    """
    cover_url = track_info.cover_url
    
    # [FIX 2] Konversi Explicit ke "True" / "False" (String)
    explicit_val = str(track_info.explicit) # Hasilnya "True" atau "False"
    
    rel_date = "Unknown"
    if track_info.tags and hasattr(track_info.tags, 'release_date') and track_info.tags.release_date:
        rel_date = str(track_info.tags.release_date)
    elif hasattr(track_info, 'release_year') and track_info.release_year:
        rel_date = str(track_info.release_year)
        
    # [FIX 3] Ambil Total Tracks & Volumes dari tags jika ada
    t_tracks = "1"
    t_vols = "1"
    if track_info.tags:
        if track_info.tags.total_tracks: t_tracks = str(track_info.tags.total_tracks)
        # Asumsi disc_total / volumes ada di tags jika API mendukung, jika tidak default 1
        # if track_info.tags.disc_total: t_vols = str(track_info.tags.disc_total)

    meta = {
        'title': track_info.name,
        'artist': track_info.artists[0] if track_info.artists else "Unknown",
        'album': track_info.album,
        'albumartist': track_info.tags.album_artist if track_info.tags else "Unknown",
        
        # Date & Year
        'date': str(track_info.release_year) if track_info.release_year else "",
        'release_date': rel_date,
        
        # Track Info (LENGKAPI KEY DI SINI)
        'tracknumber': str(track_info.tags.track_number) if track_info.tags else "1",
        'totaltracks': t_tracks, 
        'discnumber': str(track_info.tags.disc_number) if track_info.tags else "1",
        'totalvolumes': t_vols,
        
        # Genre & Misc
        'genre': "Pop", 
        'duration': track_info.duration, 
        
        # Caption Info
        'quality': "High (320kbps)",
        'provider': "Spotify",
        'explicit': explicit_val, # Sekarang berisi "True" / "False"
        
        # System
        'type': 'track',
        'cover': cover_url,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if is_episode:
        meta['type'] = 'episode'
        meta['album'] = track_info.album 
        meta['artist'] = track_info.artists[0] 
        
    return meta
