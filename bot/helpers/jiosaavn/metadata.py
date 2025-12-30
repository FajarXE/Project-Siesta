from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_jiosaavn_metadata(file_path, track_data, album_art_path, lyrics=None):
    try:
        audio = MP4(file_path)
        
        # Mapping Metadata Utama
        audio["\xa9nam"] = track_data.get("song", "Unknown Title")
        audio["\xa9alb"] = track_data.get("album", "Unknown Album")
        audio["\xa9ART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["aART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["\xa9day"] = str(track_data.get("year", ""))
        audio["\xa9wrt"] = track_data.get("music", "") # Composer
        
        # Metadata Tambahan (Sesuai Referensi)
        if track_data.get("label"):
            audio["----:TXXX:Record label"] = track_data["label"].encode('utf-8')
            audio["cprt"] = track_data.get("copyright_text", track_data["label"]) # Copyright
            
        if track_data.get("language"):
            audio["----:TXXX:Language"] = track_data["language"].title().encode('utf-8')
            
        # Rating (Explicit)
        if "explicit_content" in track_data:
            audio["rtng"] = [2 if int(track_data["explicit_content"]) == 0 else 4]

        # Lirik
        if lyrics:
            clean_lyrics = lyrics.replace("<br>", "\n")
            audio["\xa9lyr"] = clean_lyrics

        # Cover Art
        if album_art_path:
            with open(album_art_path, "rb") as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
        
        audio.save()
    except Exception as e:
        LOGGER.error(f"Gagal set metadata JioSaavn: {e}")
