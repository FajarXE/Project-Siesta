from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_gaana_metadata(file_path, track_data, album_art_path):
    duration = 0
    try:
        audio = MP4(file_path)
        audio.clear()

        # Basic
        audio["\xa9nam"] = track_data.get("track_title", "Unknown")
        audio["\xa9alb"] = track_data.get("album_title", "Unknown")
        
        artists = track_data.get("artist", [])
        if artists:
            artist_names = [a['name'] for a in artists]
            audio["\xa9ART"] = artist_names[0] # Primary
            # Album Artist
            audio["aART"] = artist_names[0] 
        else:
             audio["\xa9ART"] = "Unknown"
             audio["aART"] = "Unknown"

        # --- Extra Tags (Sesuai gaana.py) ---
        if track_data.get("release_date"):
            audio["\xa9day"] = track_data["release_date"]
            
        if track_data.get("gener"): # Typo di API Gaana 'gener'
            genres = [g['name'] for g in track_data["gener"]]
            if genres: audio["\xa9gen"] = genres[0]
            
        if track_data.get("isrc"):
            audio["----:com.apple.iTunes:ISRC"] = track_data["isrc"].encode('utf-8')

        if track_data.get("language"):
            audio["----:com.apple.iTunes:LANGUAGE"] = track_data["language"].title().encode('utf-8')
            
        label = track_data.get("label_name") or "Gaana"
        audio["cprt"] = label 
        audio["----:TXXX:Record label"] = label.encode('utf-8')

        # Track Number
        if track_data.get("track_number"):
             # Format trkn: (track_num, total_tracks)
             t_num = int(track_data["track_number"])
             t_cnt = int(track_data.get("track_count", 0))
             audio["trkn"] = [(t_num, t_cnt)]

        # Explicit Rating (1 = Parent Warning)
        if "parental_warning" in track_data:
             audio["rtng"] = [4 if track_data["parental_warning"] == 1 else 2]
        
        audio['stik'] = [1] # Music Media Type

        if album_art_path:
            with open(album_art_path, 'rb') as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]

        audio.save()
        
        # --- Ambil Durasi ---
        audio = MP4(file_path)
        duration = int(audio.info.length)
        
    except Exception as e:
        LOGGER.error(f"Gagal set metadata Gaana: {e}")
        
    return duration
