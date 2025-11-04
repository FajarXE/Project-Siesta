# [FILE: bot/modules/provider_settings.py]

# ... (Impor lainnya) ...
# TAMBAHKAN IMPOR INI:
from ..helpers.beatport.manager import beatport_manager

# --- MODIFIKASI DIMULAI ---
# Impor dictionary klien Qobuz yang aktif
from bot import BOT_QOBUZ_CLIENTS
# --- MODIFIKASI SELESAI ---

# ... (Fungsi provider_cb) ...

# ... (Fungsi Qobuz) ...

# ... (Fungsi Tidal) ...

# TAMBAHKAN FUNGSI BARU INI DI AKHIR FILE (SEBELUM FUNGSI TIDAL ATAU SETELAHNYA):

#----------------
# BEATPORT
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bpP"))
async def beatport_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        
        current = beatport_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Beatport:",
            markup=bp_button(quality) # Menggunakan bp_button dari settings.py
        )

@Client.on_callback_query(filters.regex(pattern=r"^bpQ"))
async def beatport_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # Map dari Teks Display -> Kunci API
        qual_map_display = {
            "Lossless (FLAC)": "lossless",
            "High (AAC 256)": "high",
            "Medium (AAC 128)": "medium"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)

        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        
        # Set kualitas baru
        beatport_manager.quality = to_set

        # Simpan ke database sebagai default baru
        await database.set_variable('BEATPORT_QUALITY', to_set)
        
        await beatport_cb(c, cb)
