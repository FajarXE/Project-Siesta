from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_jiosaavn_metadata(file_path, track_data, album_art_path):
    try:
        audio = MP4(file_path)
        
        # Basic Tags
        audio["\xa9nam"] = track_data.get("song", "Unknown Title")
        audio["\xa9alb"] = track_data.get("album", "Unknown Album")
        audio["\xa9ART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["aART"] = track_data.get("primary_artists", "Unknown Artist") # Album Artist
        audio["\xa9day"] = str(track_data.get("year", ""))
        audio["cprt"] = track_data.get("copyright_text", "")
        audio["\xa9wrt"] = track_data.get("music", "") # Composer
        
        # Cover Art
        if album_art_path:
            with open(album_art_path, "rb") as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
        
        audio.save()
    except Exception as e:
        LOGGER.error(f"Gagal set metadata JioSaavn: {e}")
