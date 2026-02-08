import os
import asyncio
import logging
from pyrogram.errors import MessageNotModified

# Import internal bot modules
from config import Config
from bot.helpers.utils import format_string, create_simple_text, post_art_poster
from bot.helpers.message import edit_message, send_message
from bot.helpers.uploder import track_upload, album_upload, playlist_upload, artist_upload
# [PERBAIKAN] Import create_cover_file agar bisa bikin thumbnail lokal
from bot.helpers.metadata import set_metadata, create_cover_file 
from bot.helpers.spotify.manager import spotify_manager
import bot.helpers.translations as lang

LOGGER = logging.getLogger("SpotifyHandler")

async def start_spotify(link: str, user: dict):
    # 1. Pastikan Manager Siap
    client = spotify_manager.get_client()
    if not client:
        # Coba init ulang jika client mati
        await spotify_manager.initialize_clients()
        client = spotify_manager.get_client()
        if not client:
            await send_message(user, "❌ **Spotify Gagal:** Bot belum login. Admin harus menjalankan `/spotify_login`.", 'text')
            return

    # 2. Parsing URL
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Menganalisis Link...")
    
    parsed_data = client.parse_url(link) # Mengembalikan (DownloadTypeEnum, item_id)
    if not parsed_data:
        await edit_message(msg, "❌ Link Spotify tidak valid atau tidak didukung.")
        return

    item_type_enum, item_id = parsed_data
    if hasattr(item_type_enum, 'name'):
        item_type = item_type_enum.name
    else:
        item_type = str(item_type_enum)

    item_type = item_type.lower() # Normalisasi ke lowercase

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
            await edit_message(msg, f"❌ Tipe konten '{item_type}' belum didukung sepenuhnya.")
            
    except Exception as e:
        LOGGER.error(f"Spotify Handler Error: {e}", exc_info=True)
        await edit_message(msg, f"❌ **Error:** {str(e)}")


async def process_track(client, track_id, user, is_episode=False):
    msg = user.get('bot_msg')
    await edit_message(msg, f"⬇️ **Spotify:** Mengunduh {'Episode' if is_episode else 'Lagu'}...")

    # A. Ambil Info Metadata (Sekarang sudah lengkap dengan codec/quality info)
    try:
        if is_episode:
             track_info = client.get_episode_info(track_id, "HIGH", None)
        else:
             track_info = client.get_track_info(track_id, "HIGH", None)
             
        if not track_info:
            raise Exception("Gagal mengambil metadata. Lagu mungkin tidak tersedia.")

        # B. Download Audio (Paksa HIGH/320kbps sesuai API yang sudah diupdate)
        download_result = None
        if is_episode:
             download_result = client.get_episode_download(track_id=track_id, quality_tier="HIGH")
        else:
             download_result = client.get_track_download(track_id=track_id, quality_tier="HIGH")

        if not download_result or not download_result.temp_file_path:
            raise Exception("Gagal mengunduh stream audio.")

        # C. Mapping Metadata
        meta = map_spotify_to_bot_metadata(track_info, user, is_episode)
        
        # D. Pindahkan File
        final_filename = f"{meta['artist']} - {meta['title']}.ogg".replace("/", "_")
        user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify"
        os.makedirs(user_folder, exist_ok=True)
        
        final_path = os.path.join(user_folder, final_filename)
        
        import shutil
        shutil.move(download_result.temp_file_path, final_path)
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder

        # E. [PERBAIKAN UTAMA] Download Thumbnail Lokal untuk Telegram
        # Telegram butuh file lokal untuk 'thumb=', bukan URL.
        if meta.get('cover'):
            thumb_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
            meta['thumb'] = thumb_path # Key ini dibaca oleh uploader.py
            
        # F. Pasang Tag Metadata (Internal File)
        await edit_message(msg, "🏷 **Spotify:** Menulis Metadata...")
        await set_metadata(meta, user['user_id'])

        # G. Upload
        await edit_message(msg, "⬆️ **Spotify:** Mengunggah...")
        await track_upload(meta, user)

    except Exception as e:
        raise e


async def process_album(client, album_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Album...")

    # Ambil Info Album
    album_info = client.get_album_info(album_id)
    if not album_info:
        raise Exception("Album tidak ditemukan.")

    tracks = album_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Album ditemukan: {album_info.name}\nJumlah Lagu: {total}")
    
    # Poster Album
    meta_album = {
        'title': album_info.name,
        'artist': album_info.artist,
        'cover': album_info.all_track_cover_jpg_url,
        'type': 'album',
        'provider': 'Spotify',
        'date': str(album_info.release_year),
        'release_date': str(album_info.release_year),
        'quality': "High (320kbps)", # Info untuk Poster
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/" # Penting untuk create_cover_file
    }
    
    # Download Poster Lokal
    if meta_album.get('cover'):
         poster_path = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
         meta_album['thumb'] = poster_path

    user['poster_msg'] = await post_art_poster(user, meta_album)

    # Loop Download
    processed_tracks = []
    
    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify/{album_info.name}"
    os.makedirs(user_folder, exist_ok=True)

    for i, track in enumerate(tracks):
        try:
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Album:** ({current_num}/{total})\n`{track.name}`")
            
            # Download Logic
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                # Map Metadata
                meta = map_spotify_to_bot_metadata(track, user)
                
                # Nama file dengan track number
                clean_title = meta['title'].replace("/", "_")
                filename = f"{str(meta['tracknumber']).zfill(2)}. {clean_title}.ogg"
                final_path = os.path.join(user_folder, filename)
                
                import shutil
                shutil.move(download_result.temp_file_path, final_path)
                
                meta['filepath'] = final_path
                meta['folderpath'] = user_folder
                
                # [PERBAIKAN] Set Thumbnail Track dari Cover Album
                meta['cover'] = album_info.all_track_cover_jpg_url
                if meta_album.get('thumb'):
                    meta['thumb'] = meta_album['thumb']
                else:
                    # Download jika belum ada
                    t_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
                    meta['thumb'] = t_path
                
                # Tagging
                await set_metadata(meta, user['user_id'])
                processed_tracks.append(meta)
                
        except Exception as e:
            LOGGER.error(f"Gagal download track {track.name}: {e}")
            continue

    if not processed_tracks:
        raise Exception("Gagal mengunduh semua lagu dalam album.")

    # Upload Album (Batch / ZIP)
    meta_album['tracks'] = processed_tracks
    meta_album['folderpath'] = user_folder
    meta_album['totaltracks'] = len(processed_tracks)
    
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

    # Poster
    meta_playlist = {
        'title': playlist_info.name,
        'artist': playlist_info.creator,
        'cover': playlist_info.cover_url,
        'type': 'playlist',
        'provider': 'Spotify',
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    # Download Poster
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
            
            # Cek episode
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
                
                # Download Thumb per track
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
    meta_playlist['totaltracks'] = len(processed_tracks)
    
    await playlist_upload(meta_playlist, user)


async def process_artist(client, artist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "⚠️ **Info:** Download Artis belum didukung penuh. Silakan download per Album.")


# --- HELPER MAPPING (PERBAIKAN UTAMA CAPTION) ---
def map_spotify_to_bot_metadata(track_info, user, is_episode=False):
    """
    Mengubah Objek TrackInfo menjadi Dictionary Metadata Bot.
    Pastikan semua key yang dibutuhkan oleh Uploader terisi.
    """
    cover_url = track_info.cover_url
    
    # Konversi Explicit ke String "Yes" / "No" untuk Caption
    explicit_val = "Yes" if track_info.explicit else "No"
    
    # Ambil Tanggal Rilis
    rel_date = "Unknown"
    if track_info.tags and hasattr(track_info.tags, 'release_date') and track_info.tags.release_date:
        rel_date = str(track_info.tags.release_date)
    elif hasattr(track_info, 'release_year') and track_info.release_year:
        rel_date = str(track_info.release_year)

    meta = {
        'title': track_info.name,
        'artist': track_info.artists[0] if track_info.artists else "Unknown",
        'album': track_info.album,
        'albumartist': track_info.tags.album_artist if track_info.tags else "Unknown",
        
        # Date & Year
        'date': str(track_info.release_year) if track_info.release_year else "",
        'release_date': rel_date,
        
        # Track Info
        'tracknumber': str(track_info.tags.track_number) if track_info.tags else "1",
        'totaltracks': str(track_info.tags.total_tracks) if track_info.tags else "1",
        'discnumber': str(track_info.tags.disc_number) if track_info.tags else "1",
        'totalvolumes': "1", # Default
        
        # Genre & Misc
        'genre': "Pop", 
        'duration': track_info.duration, 
        
        # [PENTING] Caption Quality & Provider
        'quality': "High (320kbps)", # Kita sudah paksa 320kbps di API
        'provider': "Spotify",
        'explicit': explicit_val, # String untuk Caption "Yes/No"
        
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
