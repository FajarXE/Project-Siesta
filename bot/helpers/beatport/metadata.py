# [FILE: bot/helpers/beatport/metadata.py]
# TAMBAHKAN IMPOR INI di bagian atas file:
from .manager import beatport_manager

# ... (impor lainnya) ...

# GANTI FUNGSI 'process_track_metadata' DENGAN VERSI INI:

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None):
    """Memproses metadata untuk satu lagu."""
    client: BeatportAPI = user['beatport_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # Dapatkan data lagu
    try:
        track_data = pre_data if pre_data else await client.get_track(track_id)
        if not track_data.get("is_available_for_streaming"):
             raise BeatportError(f"Track '{track_data.get('name')}' tidak streamable!")
        if track_data.get("preorder"):
            raise BeatportError(f"Track '{track_data.get('name')}' adalah pre-order!")
    except Exception as e:
        LOGGER.error(f"Beatport: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    # Dapatkan data album terkait
    album_id = track_data.get("release").get("id")
    try:
        album_data = await client.get_release(album_id)
    except Exception:
        album_data = {} # Lanjutkan meskipun album gagal (misal region locked)
    
    metadata['itemid'] = track_id
    
    # Info dasar
    title = track_data.get("name")
    if track_data.get("mix_name"):
        title += f" ({track_data.get('mix_name')})"
    metadata['title'] = title
    
    metadata['artist'] = ", ".join([a.get("name") for a in track_data.get("artists", [])])
    metadata['albumartist'] = ", ".join([a.get("name") for a in album_data.get("artists", [])])
    
    metadata['album'] = album_data.get("name")
    metadata['date'] = track_data.get("publish_date")
    metadata['tracknumber'] = str(track_data.get("number", 1))
    metadata['totaltracks'] = str(album_data.get("track_count", 1))
    
    # Info teknis
    metadata['isrc'] = track_data.get("isrc")
    metadata['upc'] = album_data.get("upc")
    metadata['duration'] = track_data.get("length_ms", 0) // 1000
    
    # Info label & genre
    release_year = track_data.get("publish_date", "N/A")[:4]
    label_name = track_data.get("release", {}).get("label", {}).get("name", "N/A")
    metadata['copyright'] = f"© {release_year} {label_name}"
    
    genres = [track_data.get("genre", {}).get("name")]
    if track_data.get("sub_genre"):
        genres.append(track_data.get("sub_genre").get("name"))
    metadata['genre'] = ", ".join(filter(None, genres))
    
    metadata['provider'] = 'Beatport'
    metadata['type'] = 'track'
    
    # Sampul
    bp_cover_url = await _generate_artwork_url(track_data.get("release").get("image").get("dynamic_uri"))
    metadata['cover'] = await _process_cover(metadata, bp_cover_url)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover_url, 80), metadata, True)

    # --- LOGIKA KUALITAS YANG DIPERBARUI ---
    
    # Dapatkan user_id dari dict 'user'
    user_id = user.get('user_id')
    if not user_id:
        LOGGER.warning(f"Beatport: user_id tidak ditemukan untuk track {track_id}, menggunakan kualitas default.")
        preferred_quality = beatport_manager.quality
    else:
        preferred_quality = beatport_manager.get_user_quality(user_id)

    LOGGER.debug(f"Beatport: Menggunakan kualitas preferensi '{preferred_quality}' untuk user {user_id} (Track: {track_id})")
    
    # Buat daftar kualitas untuk dicoba, mulai dari yang dipilih
    quality_order = []
    if preferred_quality == "lossless":
        quality_order = ["lossless", "high", "medium"]
    elif preferred_quality == "high":
        quality_order = ["high", "medium"]
    else: # medium
        quality_order = ["medium"]
    
    # Info Kualitas & Download
    stream_data = None
    quality_map_display = {
        "lossless": ("FLAC", "flac"),
        "high": ("AAC 256", "m4a"),
        "medium": ("AAC 128", "m4a")
    }
    
    for quality_key in quality_order:
        try:
            stream_data_json = await client.get_track_download(track_id, QUALITY_MAP[quality_key])
            metadata['quality'], metadata['extension'] = quality_map_display[quality_key]
            stream_data = stream_data_json # Simpan JSON respons
            LOGGER.debug(f"Beatport: Berhasil mendapatkan URL untuk kualitas {quality_key} (Track: {track_id})")
            break # Berhasil, keluar dari loop
        except Exception as e:
            LOGGER.warning(f"Beatport: Gagal mendapatkan kualitas '{quality_key}' for track {track_id}. Mencoba fallback... Error: {e}")
            continue
    
    if not stream_data:
        raise BeatportError(f"Gagal mendapatkan URL download untuk semua kualitas yang dicoba (Track: {track_id}). Mungkin masalah langganan atau region.")
        
    metadata['download_url'] = stream_data.get("location")
    if not metadata['download_url']:
        raise BeatportError(f"Gagal mendapatkan URL download (Track: {track_id}). Respons API valid, tapi URL tidak ada.")

    return metadata

# ... (Sisa file 'metadata.py' tetap sama) ...
