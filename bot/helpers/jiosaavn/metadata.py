from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_jiosaavn_metadata(file_path, track_data, album_art_path, lyrics=None):
    duration = 0
    try:
        audio = MP4(file_path)
        
        # Basic
        audio["\xa9nam"] = track_data.get("song", "Unknown Title")
        audio["\xa9alb"] = track_data.get("album", "Unknown Album")
        audio["\xa9ART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["aART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["\xa9day"] = str(track_data.get("year", ""))
        audio["\xa9wrt"] = track_data.get("music", "")
        
        # Advanced (Reference: jiosaavn.py)
        if track_data.get("label"):
            audio["----:TXXX:Record label"] = bytes(track_data["label"], 'utf-8')
            audio["cprt"] = track_data.get("copyright_text", track_data["label"])
        
        if track_data.get("language"):
            audio["----:TXXX:Language"] = bytes(track_data["language"].title(), 'utf-8')
            
        if "explicit_content" in track_data:
            audio["rtng"] = [2 if int(track_data["explicit_content"]) == 0 else 4]

        # Tag Khusus JioSaavn
        if track_data.get("singers"):
             audio["----:TXXX:Singers"] = bytes(track_data["singers"], 'utf-8')
        if track_data.get("starring"):
             audio["----:TXXX:Starring"] = bytes(track_data["starring"], 'utf-8')
        if track_data.get("featured_artists"):
             audio["----:TXXX:Featured artists"] = bytes(track_data["featured_artists"], 'utf-8')

        if lyrics:
            clean_lyrics = lyrics.replace("<br>", "\n")
            audio["\xa9lyr"] = clean_lyrics

        if album_art_path:
            with open(album_art_path, "rb") as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
        
        audio.pop("©too", None) 
        audio.save()
        
        # Get Duration
        audio = MP4(file_path)
        duration = int(audio.info.length)

    except Exception as e:
        LOGGER.error(f"Gagal set metadata JioSaavn: {e}")
    
    return duration
