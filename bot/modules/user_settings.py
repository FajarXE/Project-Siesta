# [FILE BARU: bot/handlers/user_settings.py]

import bot.helpers.translations as lang
import logging, asyncio
from traceback import format_exc

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config
from bot import cmd
# --- MODIFIKASI DIMULAI ---
# Impor daftar klien yang sudah login dari __main__.py
from bot import BOT_QOBUZ_CLIENTS 
# Impor manager Beatport
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor beatport_manager. Panel Beatport tidak akan berfungsi.")
    beatport_manager = None
# --- MODIFIKASI SELESAI ---

# --- MODIFIKASI DIMULAI ---
# Tambahkan bp_button ke impor
from ..helpers.buttons.settings import usetting_button, tidal_quality_button, qb_button, bp_button
# --- MODIFIKASI SELESAI ---
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import tidalapi
# --- MODIFIKASI DIMULAI ---
# Menghapus impor qobuz_api yang menyebabkan crash
# from ..helpers.qobuz.qopy import qobuz_api 
# --- MODIFIKASI SELESAI ---
from ..helpers.utils import fetch_zip_settings
from ..settings import bot_set
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details


@Client.on_message(filters.command(cmd.USETTING))
async def start_user_setting(client: Client, m: Message, edit=False, users_: dict=None):
    if not await check_user(msg=m):
        return
    USETTING_TEXT = """
<blockquote>
PLAYLIST_ZIP  : {playlist}
ART_POSTER    : {poster}
ALBUM_ZIP     : {album}
</blockquote>
{date}
Choose Menu option bellow:
"""
    user = await fetch_user_details(m)
    user_data = users_
    if not users_:
        user_data = user
    #logging.info(user_data["user_id"])
    PLAYLIST_ZIP, ART_POSTER, ALBUM_ZIP = await asyncio.to_thread(fetch_zip_settings, user_data)
    
    text = USETTING_TEXT.format_map({
        "album".lower(): ALBUM_ZIP,
        "poster": ART_POSTER,
        "playlist".lower(): PLAYLIST_ZIP,
        "date": m.date.now().strftime("%d/%m/%Y %H:%M:%S"),
    })
    
    if not edit:
        await send_message(user, text, markup=usetting_button())
        return
    await edit_message(m, text, markup=usetting_button())


@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz|close|beatport)")) # <-- MODIFIKASI DI SINI
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
        text = f"Choose Tidal Audio Quality bellow:"
        qualities = {
              'LOW': 'LOW',
              'HIGH': 'HIGH',
              'LOSSLESS': 'LOSSLESS'
        }
        user_dict = tidalapi.user_data.get(user_id, {})
        qual = user_dict.get("tidal_qual", tidalapi.quality)
        if tidalapi.mobile_hires:
            qualities['HI_RES'] = 'MAX'
        qualities[qual] += '✅'
        return await edit_message(query.message, text, tidal_quality_button(qualities, user_id))
    
    # --- MODIFIKASI DIMULAI: Memperbaiki logika Qobuz ---
    if data[1] == "qobuz" or datatype == "qobuz":
        text = f"Choose Qobuz Audio Quality bellow:"
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}

        # Periksa apakah ada klien Qobuz yang aktif
        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(query.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        
        # Ambil klien Qobuz pertama yang tersedia untuk *membaca* pengaturan
        # (Kita asumsikan pengaturan pengguna konsisten di semua klien)
        client_to_check = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]

        user_dict = client_to_check.user_data.get(user_id, {})
        current = user_dict.get("qobuz_qual", client_to_check.quality) # Baca kualitas default dari instansi
        quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text,
            markup=qb_button(quality, user_id)
        )
    # --- MODIFIKASI SELESAI ---

    # --- TAMBAHAN DIMULAI: Logika Beatport ---
    if data[1] == "beatport" or datatype == "beatport":
        text = f"Choose Beatport Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }

        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(query.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        
        # Dapatkan pengaturan pengguna dari cache manager
        user_dict = beatport_manager.user_data.get(user_id, {})
        # Fallback ke kualitas default admin jika pengguna tidak punya pengaturan
        current = user_dict.get("beatport_qual", beatport_manager.quality) 
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text,
            markup=bp_button(quality, user_id) # Menggunakan bp_button (mode user)
        )
    # --- TAMBAHAN SELESAI ---


@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    to_set = query.data.split('_')[1]
    user_id = query.from_user.id
    #logging.info((to_set, query.data))
    try:
        if to_set == 'spatial':
            #options = ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']
            # assuming atleast tv session is added
            options = ['OFF', 'ATMOS AC3 JOC']
            if tidalapi.mobile_atmos:
                options.append('ATMOS AC4')
            if tidalapi.mobile_atmos or tidalapi.mobile_hires:
                options.append('Sony 360RA')
    
            user_dict = tidalapi.user_data.get(user_id, {})
            spatial = user_dict.get("tidal_spatial", tidalapi.spatial)
            #logging.info((spatial, options))
            try:
                current = options.index(spatial)
            except:
                current = 0
                
            nexti = (current + 1) % 4
            await tidalapi.setup_quality(user_id=query.from_user.id, spatial=options[nexti])
            await database.save_user_settings(query.from_user.id, tidalapi.user_data[query.from_user.id])
            #logging.info("abc")
            return await uset_cb(client, query, "tidal")
            #tidalapi.spatial = options[nexti]
            #logging.info((options, nexti)) # Debugging
            #await database.set_variable('TIDAL_SPATIAL', options[nexti])
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            #logging.info(to_set)
            #tidalapi.quality = to_set
            await tidalapi.setup_quality(user_id=query.from_user.id, qual=to_set)
            await database.save_user_settings(query.from_user.id, tidalapi.user_data[query.from_user.id])
            return await uset_cb(client, query, "tidal")
    except Exception:
        logging.error(format_exc())

@Client.on_callback_query(filters.regex("^uqbs"))
async def uset_qobuz(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qobuz = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
    to_set = query.data.split('_')[1]
    qobuz_qual = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]

    # --- MODIFIKASI DIMULAI: Menyimpan pengaturan ke SEMUA klien aktif ---
    if not BOT_QOBUZ_CLIENTS:
        await query.answer("Layanan Qobuz tidak aktif!", show_alert=True)
        return

    user_data_to_save = {}
    
    # Loop ke semua klien bot yang aktif dan terapkan pengaturan
    for client_instance in BOT_QOBUZ_CLIENTS.values():
        await client_instance.setup_quality(query.from_user.id, qobuz_qual)
        # Ambil data pengguna yang baru disimpan dari klien
        user_data_to_save = client_instance.user_data.get(query.from_user.id, {})

    # Simpan pengaturan pengguna ke database
    if user_data_to_save:
        # Pendekatan yang lebih aman:
        current_user_data = await database.get_user_settings(query.from_user.id)
        if not current_user_data:
            current_user_data = {}
        current_user_data.update(user_data_to_save)
        await database.save_user_settings(query.from_user.id, current_user_data)
    # --- MODIFIKASI SELESAI ---

    await uset_cb(client, query, "qobuz")


# --- TAMBAHAN DIMULAI: Handler untuk User Beatport ---
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
    
    # Dapatkan data pengguna yang baru disimpan dari manager
    user_data_to_save = beatport_manager.user_data.get(user_id, {})

    # Simpan pengaturan pengguna ke database
    if user_data_to_save:
        # Pendekatan yang lebih aman:
        # 1. Ambil data user yang ada
        current_user_data = await database.get_user_settings(user_id)
        if not current_user_data:
            current_user_data = {}
        
        # 2. Update hanya bagian beatport (atau semua cache dari manager)
        current_user_data.update(user_data_to_save)
        
        # 3. Simpan kembali
        await database.save_user_settings(user_id, current_user_data)
    
    # Panggil kembali fungsi panel utama untuk me-refresh tampilan
    await uset_cb(client, query, "beatport")
# --- TAMBAHAN SELESAI ---


@Client.on_callback_query(filters.regex("^zip"))
async def uset_zip(self, query):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")[1].lower()
    user_id = query.from_user.id
    users_ = {"user_id": user_id}
    if data == "playlist":
        user_dict = bot_set.user_data.get(user_id, {})
        playlist_zip = user_dict.get("playlist_zip", False)
        data_saved = {"PLAYLIST_ZIP".lower(): not playlist_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Playlist zip: {data_saved['playlist_zip']}")
        #logging.info("playlist")
        return await start_user_setting(self, query.message, True, users_)
    if data == "album":
        user_dict = bot_set.user_data.get(user_id, {})
        album_zip = user_dict.get("album_zip", False)
        data_saved = {"ALBUM_ZIP".lower(): not album_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Album zip: {data_saved['album_zip']}")
        return await start_user_setting(self, query.message, True, users_)
        #logging.info("album")
    if data == "artist":
        user_dict = bot_set.user_data.get(user_id, {})
        artist_zip = user_dict.get("artist_zip", False)
        data_saved = {"ARTIST_ZIP".lower(): not artist_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Artist zip: {data_saved['artist_zip']}")
        #logging.info("artist")
        return await start_user_setting(self, query.message, True, users_)
    if data == "poster":
        user_dict = bot_set.user_data.get(user_id, {})
        art_poster = user_dict.get("art_poster", False)
        data_saved = {"art_poster": not art_poster}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Art poster: {data_saved['art_poster']}")
        return await start_user_setting(self, query.message, True, users_)


@Client.on_message(filters.command("debug") & filters.user(list(Config.ADMINS)))
async def debug(c, m): # debugger
    # --- MODIFIKASI DIMULAI: Memperbaiki debug Qobuz ---
    dt_qb = "QOBUZ:\n"
    if BOT_QOBUZ_CLIENTS:
        # Ambil klien pertama untuk ditampilkan
        first_client = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]
        dt_qb += f"{len(BOT_QOBUZ_CLIENTS)} klien Qobuz aktif.\n"
        dt_qb += f"Label Klien #1: {first_client.label}\n"
        dt_qb += f"Kualitas Default Klien #1: {first_client.quality}"
    else:
        dt_qb += "Tidak ada klien Qobuz yang aktif."
    # --- MODIFIKASI SELESAI ---

    # --- TAMBAHAN: Info debug Beatport ---
    dt_bp = "\n\nBEATPORT:\n"
    if beatport_manager and beatport_manager.clients:
        dt_bp += f"{len(beatport_manager.clients)} klien Beatport aktif.\n"
        dt_bp += f"Kualitas Default: {beatport_manager.quality}\n"
        dt_bp += f"Cache User: {len(beatport_manager.user_data)} pengguna"
    else:
        dt_bp += "Tidak ada klien Beatport yang aktif."
    # --- TAMBAHAN SELESAI ---

    dt_td = f"\n\nTIDAL:\n{bot_set.tidal}\n{bot_set.tidal}\n{bot_set.tidal}"
    zips = f"\n\n{bot_set.album_zip}"
    user_dict = bot_set.user_data
    zips += f"\n\n{user_dict}"
    await m.reply(dt_qb + dt_bp + dt_td + zips, True) # <-- Ditambahkan dt_bp
