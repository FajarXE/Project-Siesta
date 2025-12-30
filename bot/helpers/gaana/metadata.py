from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_gaana_metadata(file_path, track_data, album_art_path):
    try:
        audio = MP4(file_path)
        audio.clear()

        # Basic
        audio["\xa9nam"] = track_data.get("track_title", "Unknown")
        audio["\xa9alb"] = track_data.get("album_title", "Unknown")
        
        artists = track_data.get("artist", [])
        artist_name = artists[0]['name'] if artists else "Unknown"
        audio["\xa9ART"] = artist_name
        audio["aART"] = artist_name

        # Extra Metadata (Sesuai Reference gaana.py)
        if track_data.get("release_date"):
            audio["\xa9day"] = track_data["release_date"]
            
        if track_data.get("isrc"):
            audio["----:com.apple.iTunes:ISRC"] = track_data["isrc"].encode('utf-8')

        if track_data.get("language"):
            audio["----:com.apple.iTunes:LANGUAGE"] = track_data["language"].title().encode('utf-8')
            
        # Label / Copyright (Gaana sering pakai key 'label_name' atau dari album detail)
        # Kita ambil yang tersedia
        label = track_data.get("label_name") or "Gaana"
        audio["cprt"] = label # Copyright field
        audio["----:TXXX:Record label"] = label.encode('utf-8')

        if album_art_path:
            with open(album_art_path, 'rb') as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]

        audio.save()
    except Exception as e:
        LOGGER.error(f"Gagal set metadata Gaana: {e}")
