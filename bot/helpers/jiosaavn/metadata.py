from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_jiosaavn_metadata(file_path, track_data, album_art_path, lyrics=None):
    duration = 0
    try:
        audio = MP4(file_path)
        
        # --- 1. Basic Tags ---
        # Menggunakan unescape tidak diperlukan di sini karena response API json biasanya sudah utf-8
        audio["\xa9nam"] = track_data.get("song", "Unknown Title")
        audio["\xa9alb"] = track_data.get("album", "Unknown Album")
        audio["\xa9ART"] = track_data.get("primary_artists", "Unknown Artist")
        audio["aART"] = track_data.get("primary_artists", "Unknown Artist") # Album Artist
        audio["\xa9day"] = str(track_data.get("year", ""))
        audio["\xa9wrt"] = track_data.get("music", "") # Composer
        
        # --- 2. Advanced Tags (Sesuai jiosaavn.py) ---
        # Label & Copyright
        if track_data.get("label"):
            audio["----:TXXX:Record label"] = track_data["label"].encode('utf-8')
            audio["cprt"] = track_data.get("copyright_text", track_data["label"])
        
        # Language
        if track_data.get("language"):
            audio["----:TXXX:Language"] = track_data["language"].title().encode('utf-8')
            
        # Explicit Rating
        # 2 = Clean, 4 = Explicit (Apple style)
        if "explicit_content" in track_data:
            audio["rtng"] = [2 if int(track_data["explicit_content"]) == 0 else 4]

        # Singers (Custom Tag)
        singers = track_data.get("singers", "")
        if len(singers) > 1:
             audio["----:TXXX:Singers"] = singers.encode('utf-8')

        # Starring (Custom Tag)
        starring = track_data.get("starring", "")
        if len(starring) > 1:
             audio["----:TXXX:Starring"] = starring.encode('utf-8')
             
        # Featured Artists
        featured = track_data.get("featured_artists", "")
        if len(featured) > 1:
             audio["----:TXXX:Featured artists"] = featured.encode('utf-8')

        # Lyrics
        if lyrics:
            clean_lyrics = lyrics.replace("<br>", "\n")
            audio["\xa9lyr"] = clean_lyrics

        # Cover Art
        if album_art_path:
            with open(album_art_path, "rb") as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
        
        audio.pop("©too", None) # Hapus encoded by
        audio.save()
        
        # --- 3. Ambil Durasi untuk Telegram ---
        # Re-open untuk membaca info durasi yang akurat setelah save
        audio = MP4(file_path)
        duration = int(audio.info.length)

    except Exception as e:
        LOGGER.error(f"Gagal set metadata JioSaavn: {e}")
    
    return duration
