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
            audio["\xa9ART"] = artist_names[0] 
            audio["aART"] = artist_names[0]
            audio["\xa9wrt"] = ", ".join(artist_names) 
        else:
             audio["\xa9ART"] = "Unknown"
             audio["aART"] = "Unknown"

        if track_data.get("release_date"):
            audio["\xa9day"] = track_data["release_date"]
            
        if track_data.get("gener"): 
            genres = [g['name'] for g in track_data["gener"]]
            if genres: audio["\xa9gen"] = genres[0]
            
        if track_data.get("isrc"):
            audio["----:com.apple.iTunes:ISRC"] = bytes(track_data["isrc"], 'utf-8')

        if track_data.get("language"):
            audio["----:com.apple.iTunes:LANGUAGE"] = bytes(track_data["language"], 'utf-8')
            
        label = track_data.get("label_name") or "Gaana"
        audio["cprt"] = label 
        audio["----:TXXX:Record label"] = bytes(label, 'utf-8')

        # --- FIX NOMOR TRACK ---
        # Kita ambil langsung dari 'track_number' di data API asli
        # (Bukan urutan playlist 1,2,3... kecuali memang di albumnya urutan itu)
        # Handler sudah tidak menimpa 'track_number' dengan index loop.
        if track_data.get("track_number"):
             try:
                 t_num = int(track_data["track_number"])
                 # Total count biasanya per album, bukan per playlist
                 # Gaana tidak selalu kirim total_track album di object lagu
                 # Jadi kita pakai 0 jika tidak ada
                 t_cnt = 0 
                 audio["trkn"] = [(t_num, t_cnt)]
             except: pass

        if "parental_warning" in track_data:
             audio["rtng"] = [4 if track_data["parental_warning"] == 1 else 2]
        
        audio['stik'] = [1] 

        # Pasang Cover (Unique Path dari Handler)
        if album_art_path and os.path.exists(album_art_path):
            with open(album_art_path, 'rb') as f:
                audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]

        audio.save()
        
        audio = MP4(file_path)
        duration = int(audio.info.length)
        
    except Exception as e:
        LOGGER.error(f"Gagal set metadata Gaana: {e}")
        
    return duration
