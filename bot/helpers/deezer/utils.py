import aiohttp
from bot.logger import LOGGER

# URL API untuk lirik. Anda bisa mengganti ini jika punya yang lebih baik.
LYRICS_API_URL = "https://some-lyrics-api.com/lyrics?isrc=" 
# Catatan: URL di atas hanya contoh. Mari kita gunakan API yang lebih umum.
# Menggunakan API lirik yang sering dipakai di proyek serupa:
LYRICS_API_URL = "https://api.lyrics.ovh/v1/" # Format: {artist}/{title}
# API lain: https://lyrics-api.lrt.lt/lyrics/ (pakai ISRC)
LYRICS_LRT_API_URL = "https://lyrics-api.lrt.lt/lyrics/"


async def get_lrc(track_data: dict):
    """
    Mencoba mengambil lirik menggunakan ISRC atau Artis/Judul.
    track_data adalah kamus metadata yang sudah kita proses.
    """
    isrc = track_data.get('isrc')
    artist = track_data.get('artist')
    title = track_data.get('title')
    
    lyrics = "" # Default lirik kosong

    # --- Metode 1: Coba dengan ISRC (jika API mendukungnya) ---
    if isrc:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{LYRICS_LRT_API_URL}{isrc}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('lyrics'):
                            LOGGER.info(f"Mendapatkan lirik untuk ISRC {isrc} via LRT")
                            return data['lyrics']
        except Exception as e:
            LOGGER.warning(f"Gagal mengambil lirik ISRC {isrc} dari LRT: {e}")

    # --- Metode 2: Fallback ke Artis/Judul (jika ISRC gagal atau tidak ada) ---
    if artist and title:
        try:
            # Ganti spasi dengan %20 untuk URL
            artist_url = artist.replace(" ", "%20")
            title_url = title.replace(" ", "%20")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{LYRICS_API_URL}{artist_url}/{title_url}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('lyrics'):
                            LOGGER.info(f"Mendapatkan lirik untuk {artist} - {title} via Lyrics.ovh")
                            return data['lyrics'].replace("\r\n\r\n", "\n").strip()
        except Exception as e:
            LOGGER.warning(f"Gagal mengambil lirik Artis/Judul dari Lyrics.ovh: {e}")

    LOGGER.info(f"Tidak ditemukan lirik untuk {artist} - {title}")
    return lyrics # Kembalikan lirik kosong jika semua gagal

