# [FILE: bot/modules/user_settings.py]

# ... (Impor lainnya) ...
# TAMBAHKAN IMPOR INI:
from ..helpers.beatport.manager import beatport_manager

# ... (Impor lainnya) ...
from ..helpers.buttons.settings import usetting_button, tidal_quality_button, qb_button, bp_button # <-- TAMBAHKAN bp_button
from ..helpers.database.mongo_async import database
# ... (Impor lainnya) ...

# ... (Fungsi start_user_setting) ...

# UBAH 'uset_cb' (HANYA 2 baris):
@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz|close|beatport)")) # <-- TAMBAHKAN |beatport
async def uset_cb(client, query, datatype=""):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")
    user_id = query.from_user.id
    #logging.info(data)
    if data[1] == "back":
        users_ = {"user_id": user_id}
        return await start_user_setting(client, query.message, True, users_)
    if data[1] == "close":
        await query.message.delete()
    if data[1] == "tidal" or datatype == "tidal": #(datatype == "tidal" and data[0] == "utdqs"):
        # ... (Logika Tidal tetap sama) ...
        pass # Placeholder
    
    # --- MODIFIKASI DIMULAI: Memperbaiki logika Qobuz ---
    if data[1] == "qobuz" or datatype == "qobuz":
        # ... (Logika Qobuz tetap sama) ...
        pass # Placeholder

    # --- TAMBAHAN: Logika Beatport ---
    if data[1] == "beatport" or datatype == "beatport":
        text = f"Choose Beatport Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }

        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(query.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        
        user_dict = beatport_manager.user_data.get(user_id, {})
        current = user_dict.get("beatport_qual", beatport_manager.quality) # Baca default dari manager
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text,
            markup=bp_button(quality, user_id) # Menggunakan bp_button dengan user_id
        )
    # --- MODIFIKASI SELESAI ---


# ... (Fungsi uset_tidal) ...

# ... (Fungsi uset_qobuz) ...

# TAMBAHKAN FUNGSI BARU INI:
@Client.on_callback_query(filters.regex("^ubps")) # User BeatPort Set
async def uset_beatport(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    # Map dari Teks Display -> Kunci API
    qual_map_display = {
        "Lossless (FLAC)": "lossless",
        "High (AAC 256)": "high",
        "Medium (AAC 128)": "medium"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)

    if not beatport_manager or not beatport_manager.clients:
        await query.answer("Layanan Beatport tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # Simpan pengaturan pengguna ke cache manager
    await beatport_manager.setup_quality(user_id, to_set)
    user_data_to_save = beatport_manager.user_data.get(user_id, {})

    # Simpan pengaturan pengguna ke database
    if user_data_to_save:
        # Kita hanya perlu menyimpan bagian beatport, tapi menyimpan semuanya (termasuk tidal/qobuz) juga tidak masalah
        await database.save_user_settings(user_id, user_data_to_save)

    await uset_cb(client, query, "beatport")

# ... (Fungsi uset_zip dan debug) ...
