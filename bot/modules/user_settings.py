# [GANTI FILE: bot/modules/user_settings.py]

import bot.helpers.translations as lang
import logging, asyncio
from traceback import format_exc

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config
from bot import cmd
from bot import BOT_QOBUZ_CLIENTS 
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor beatport_manager.")
    beatport_manager = None
try:
    from ..helpers.deezer.manager import deezer_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor deezer_manager.")
    deezer_manager = None
try:
    from ..helpers.tidal.manager import tidal_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor tidal_manager.")
    tidal_manager = None
try:
    from ..helpers.kkbox.manager import kkbox_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor kkbox_manager.")
    kkbox_manager = None

# --- TAMBAHAN: Impor Manajer Beatsource ---
try:
    from ..helpers.beatsource.manager import beatsource_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor beatsource_manager.")
    beatsource_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN: Impor Manajer Soundcloud ---
try:
    from ..helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor soundcloud_manager.")
    soundcloud_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Napster ---
try:
    from ..helpers.napster.manager import napster_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor napster_manager.")
    napster_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Idagio ---
try:
    from ..helpers.idagio.manager import idagio_manager
except ImportError:
    logging.warning("UserSettings: Gagal mengimpor idagio_manager.")
    idagio_manager = None
# --- BATAS TAMBAHAN ---

from ..helpers.buttons.settings import (
    usetting_button, tidal_quality_button, 
    qb_button, bp_button, dz_button, kk_button,
    bs_button, sc_button, np_button, id_button # <-- TAMBAHKAN ID_BUTTON
)
from ..helpers.database.mongo_async import database
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


# --- MODIFIKASI: Tambahkan 'idagio' ke regex ---
@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz|close|beatport|deezer|kkbox|beatsource|soundcloud|napster|idagio)"))
async def uset_cb(client, query, datatype=""):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")
    user_id = query.from_user.id

    if data[1] == "back":
        users_ = {"user_id": user_id}
        return await start_user_setting(client, query.message, True, users_)
    if data[1] == "close":
        await query.message.delete()
        
    if data[1] == "tidal" or datatype == "tidal":
        if not tidal_manager or not tidal_manager.clients:
            return await edit_message(query.message, "Layanan Tidal tidak aktif (tidak ada klien yang login).")
        text = f"Choose Tidal Audio Quality bellow:"
        qualities = {
              'LOW': 'LOW',
              'HIGH': 'HIGH',
              'LOSSLESS': 'LOSSLESS'
        }
        # --- PERBAIKAN: Baca pengaturan dari bot_set ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        user_qual = main_user_dict.get("tidal_qual", tidal_manager.quality)
        user_spatial = main_user_dict.get("tidal_spatial", tidal_manager.spatial)
        # --- BATAS PERBAIKAN ---
        
        if any(c.mobile_hires for c in tidal_manager.clients):
            qualities['HI_RES'] = 'MAX'
        qualities[user_qual] += '✅'
        return await edit_message(query.message, text, tidal_quality_button(qualities, user_id, spatial=user_spatial))
    
    if data[1] == "qobuz" or datatype == "qobuz":
        text = f"Choose Qobuz Audio Quality bellow:"
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(query.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        client_to_check = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]

        # --- PERBAIKAN: Baca pengaturan dari bot_set ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("qobuz_qual", client_to_check.quality) 
        # --- BATAS PERBAIKAN ---
        
        quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=qb_button(quality, user_id))

    if data[1] == "beatport" or datatype == "beatport":
        text = f"Choose Beatport Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(query.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")

        # --- PERBAIKAN: Baca pengaturan dari bot_set dan sinkronkan ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("beatport_qual", beatport_manager.quality) 
        await beatport_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        # --- BATAS PERBAIKAN ---
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=bp_button(quality, user_id))

    if data[1] == "beatsource" or datatype == "beatsource":
        text = f"Choose Beatsource Audio Quality bellow:"
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(query.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        # --- PERBAIKAN: Baca pengaturan dari bot_set dan sinkronkan ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("beatsource_qual", beatsource_manager.quality) 
        await beatsource_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        # --- BATAS PERBAIKAN ---
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text + "\n(Kualitas tergantung langganan akun bot)",
            markup=bs_button(quality, user_id)
        )
    
    if data[1] == "soundcloud" or datatype == "soundcloud":
        text = f"Choose Soundcloud Audio Quality bellow:"
        quality = {
            "original": "Original (Jika Ada)",
            "stream": "Stream (Default AAC/MP3)"
        }
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(query.message, "Layanan Soundcloud tidak aktif.")
        
        # --- PERBAIKAN: Baca pengaturan dari bot_set dan sinkronkan ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("soundcloud_qual", soundcloud_manager.quality) 
        await soundcloud_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        # --- BATAS PERBAIKAN ---
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        return await edit_message(
            query.message,
            text,
            markup=sc_button(quality, user_id)
        )

    if data[1] == "deezer" or datatype == "deezer":
        text = f"Choose Deezer Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "MP3 320",
            "MP3_128": "MP3 128"
        }
        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(query.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")

        # --- PERBAIKAN: Baca pengaturan dari bot_set dan sinkronkan ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("deezer_qual", deezer_manager.quality) 
        await deezer_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        # --- BATAS PERBAIKAN ---
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=dz_button(quality, user_id))

    if data[1] == "kkbox" or datatype == "kkbox":
        text = f"Choose KKBox Audio Quality bellow:"
        quality = {
            "128k": "MP3 128k",
            "192k": "MP3 192k",
            "320k": "AAC 320k",
            "hifi": "FLAC 16-bit",
            "hires": "FLAC 24-bit"
        }
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(query.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")

        # --- PERBAIKAN: Baca pengaturan dari bot_set dan sinkronkan ---
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("kkbox_qual", kkbox_manager.quality) 
        await kkbox_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        # --- BATAS PERBAIKAN ---
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=kk_button(quality, user_id))

    # --- TAMBAHAN BARU: Blok Napster ---
    if data[1] == "napster" or datatype == "napster":
        text = f"Choose Napster Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC (HiRes/Lossless)",
            "MP3_320": "AAC 320k",
            "MP3_192": "AAC 192k",
            "MP3_128": "AAC 128k",
            "MP3_64": "HE-AAC 64k"
        }
        if not napster_manager or not napster_manager.clients:
            return await edit_message(query.message, "Layanan Napster tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("napster_qual", napster_manager.quality) 
        await napster_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text + "\n(Kualitas akhir tergantung langganan akun bot)", markup=np_button(quality, user_id))
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Idagio ---
    if data[1] == "idagio" or datatype == "idagio":
        text = f"Choose Idagio Audio Quality bellow:"
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "AAC 320k",
            "MP3_160": "AAC 160k"
        }
        if not idagio_manager or not idagio_manager.clients:
            return await edit_message(query.message, "Layanan Idagio tidak aktif (tidak ada klien yang login).")
        
        main_user_dict = bot_set.user_data.get(user_id, {})
        current = main_user_dict.get("idagio_qual", idagio_manager.quality) 
        await idagio_manager.setup_quality(user_id, current) # Sinkronkan ke cache lokal
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        return await edit_message(query.message, text, markup=id_button(quality, user_id))
    # --- BATAS TAMBAHAN ---


@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    to_set = query.data.split('_')[1]
    user_id = query.from_user.id
    if not tidal_manager or not tidal_manager.clients:
        await query.answer("Layanan Tidal tidak aktif!", show_alert=True)
        return
    try:
        if to_set == 'spatial':
            options = ['OFF', 'ATMOS AC3 JOC']
            if any(c.mobile_atmos for c in tidal_manager.clients):
                options.append('ATMOS AC4')
            if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients):
                options.append('Sony 360RA')
                
            # --- PERBAIKAN: Baca dari bot_set ---
            main_user_dict = bot_set.user_data.get(user_id, {})
            user_spatial = main_user_dict.get("tidal_spatial", tidal_manager.spatial)
            # --- BATAS PERBAIKAN ---
            
            try:
                current = options.index(user_spatial)
            except:
                current = 0
            nexti = (current + 1) % len(options) 
            
            # --- PERBAIKAN: Simpan ke bot_set dan DB ---
            bot_set.user_data.setdefault(user_id, {})["tidal_spatial"] = options[nexti]
            await database.set_variable(user_id, "tidal_spatial", options[nexti], True)
            # --- BATAS PERBAIKAN ---
            
            return await uset_cb(client, query, "tidal")
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set_qual = list(filter(lambda x: qualities[x] == to_set, qualities))[0]

            # --- PERBAIKAN: Simpan ke bot_set dan DB ---
            bot_set.user_data.setdefault(user_id, {})["tidal_qual"] = to_set_qual
            await database.set_variable(user_id, "tidal_qual", to_set_qual, True)
            # --- BATAS PERBAIKAN ---
            
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
    if not BOT_QOBUZ_CLIENTS:
        await query.answer("Layanan Qobuz tidak aktif!", show_alert=True)
        return

    # --- PERBAIKAN: Simpan ke bot_set dan DB ---
    user_id = query.from_user.id
    bot_set.user_data.setdefault(user_id, {})["qobuz_qual"] = qobuz_qual
    await database.set_variable(user_id, "qobuz_qual", qobuz_qual, True)
    # --- BATAS PERBAIKAN ---
    
    await uset_cb(client, query, "qobuz")


@Client.on_callback_query(filters.regex("^ubps")) # User BeatPort Set
async def uset_beatport(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
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
    
    # --- PERBAIKAN: Simpan ke bot_set dan DB, lalu sinkronkan ke manajer ---
    await beatport_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['beatport_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'beatport_qual', to_set, True) # Simpan ke DB
    # --- BATAS PERBAIKAN ---
    
    await uset_cb(client, query, "beatport")

@Client.on_callback_query(filters.regex("^usbs")) # User BeatSource Set
async def uset_beatsource(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    qual_map_display = {
        "Lossless (FLAC)": "lossless",
        "High (AAC 256)": "high",
        "Medium (AAC 128)": "medium"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)

    if not beatsource_manager or not beatsource_manager.clients:
        await query.answer("Layanan Beatsource tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # --- PERBAIKAN: Simpan ke bot_set dan DB, lalu sinkronkan ke manajer ---
    await beatsource_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['beatsource_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'beatsource_qual', to_set, True) # Simpan ke DB
    # --- BATAS PERBAIKAN ---
    
    await uset_cb(client, query, "beatsource")

@Client.on_callback_query(filters.regex("^uscs")) # User SoundCloud Set
async def uset_soundcloud(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    
    qual_map_display = {
        "Original (Jika Ada)": "original",
        "Stream (Default AAC/MP3)": "stream"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)

    if not soundcloud_manager or not soundcloud_manager.get_client():
        await query.answer("Layanan Soundcloud tidak aktif!", show_alert=True)
        return

    user_id = query.from_user.id
    
    # --- PERBAIKAN: Simpan ke bot_set dan DB, lalu sinkronkan ke manajer ---
    await soundcloud_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['soundcloud_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'soundcloud_qual', to_set, True) # Simpan ke DB
    # --- BATAS PERBAIKAN ---
    
    await uset_cb(client, query, "soundcloud")

@Client.on_callback_query(filters.regex("^udzs")) # User DeeZer Set
async def uset_deezer(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC": "FLAC",
        "MP3 320": "MP3_320",
        "MP3 128": "MP3_128"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not deezer_manager or not deezer_manager.clients:
        await query.answer("Layanan Deezer tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id

    # --- PERBAIKAN: Simpan ke bot_set dan DB, lalu sinkronkan ke manajer ---
    await deezer_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['deezer_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'deezer_qual', to_set, True) # Simpan ke DB
    # --- BATAS PERBAIKAN ---
    
    await uset_cb(client, query, "deezer")


@Client.on_callback_query(filters.regex("^ukks")) # User KKBox Set
async def uset_kkbox(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "MP3 128k": "128k",
        "MP3 192k": "192k",
        "AAC 320k": "320k",
        "FLAC 16-bit": "hifi",
        "FLAC 24-bit": "hires"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not kkbox_manager or not kkbox_manager.clients:
        await query.answer("Layanan KKBox tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    # --- PERBAIKAN: Simpan ke bot_set dan DB, lalu sinkronkan ke manajer ---
    await kkbox_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['kkbox_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'kkbox_qual', to_set, True) # Simpan ke DB
    # --- BATAS PERBAIKAN ---

    await uset_cb(client, query, "kkbox")

# --- TAMBAHAN BARU: Fungsi Napster ---
@Client.on_callback_query(filters.regex("^unps")) # User Napster Set
async def uset_napster(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC (HiRes/Lossless)": "FLAC",
        "AAC 320k": "MP3_320",
        "AAC 192k": "MP3_192",
        "AAC 128k": "MP3_128",
        "HE-AAC 64k": "MP3_64"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not napster_manager or not napster_manager.clients:
        await query.answer("Layanan Napster tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await napster_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['napster_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'napster_qual', to_set, True) # Simpan ke DB

    await uset_cb(client, query, "napster")
# --- BATAS TAMBAJAN ---

# --- TAMBAHAN BARU: Fungsi Idagio ---
@Client.on_callback_query(filters.regex("^uids")) # User Idagio Set
async def uset_idagio(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qual_map_display = {
        "FLAC": "FLAC",
        "AAC 320k": "MP3_320",
        "AAC 160k": "MP3_160"
    }
    to_set_display = query.data.split('_')[1]
    to_set = qual_map_display.get(to_set_display)
    if not to_set:
        return await query.answer("Kualitas tidak valid.", True)
    if not idagio_manager or not idagio_manager.clients:
        await query.answer("Layanan Idagio tidak aktif!", show_alert=True)
        return
    user_id = query.from_user.id
    
    await idagio_manager.setup_quality(user_id, to_set) # Sinkronkan ke cache lokal
    bot_set.user_data.setdefault(user_id, {})['idagio_qual'] = to_set # Simpan ke cache utama
    await database.set_variable(user_id, 'idagio_qual', to_set, True) # Simpan ke DB

    await uset_cb(client, query, "idagio")
# --- BATAS TAMBAJAN ---


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
    if data == "artist":
        user_dict = bot_set.user_data.get(user_id, {})
        artist_zip = user_dict.get("artist_zip", False)
        data_saved = {"ARTIST_ZIP".lower(): not artist_zip}
        if user_id not in bot_set.user_data:
            bot_set.user_data.setdefault(user_id, {})
        bot_set.user_data[user_id].update(data_saved)
        await database.save_user_settings(user_id, data_saved)
        await query.answer(f"Artist zip: {data_saved['artist_zip']}")
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
    dt_qb = "QOBUZ:\n"
    if BOT_QOBUZ_CLIENTS:
        first_client = BOT_QOBUZ_CLIENTS.get(1) or list(BOT_QOBUZ_CLIENTS.values())[0]
        dt_qb += f"{len(BOT_QOBUZ_CLIENTS)} klien Qobuz aktif.\n"
        dt_qb += f"Label Klien #1: {first_client.label}\n"
        dt_qb += f"Kualitas Default Klien #1: {first_client.quality}"
    else:
        dt_qb += "Tidak ada klien Qobuz yang aktif."

    dt_bp = "\n\nBEATPORT:\n"
    if beatport_manager and beatport_manager.clients:
        dt_bp += f"{len(beatport_manager.clients)} klien Beatport aktif.\n"
        dt_bp += f"Kualitas Default: {beatport_manager.quality}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_bp += f"Cache User (Global): {len([u for u in bot_set.user_data if 'beatport_qual' in bot_set.user_data[u]])} pengguna"
        # --- BATAS PERBAIKAN ---
    else:
        dt_bp += "Tidak ada klien Beatport yang aktif."

    dt_bs = "\n\nBEATSOURCE:\n"
    if beatsource_manager and beatsource_manager.clients:
        dt_bs += f"{len(beatsource_manager.clients)} klien Beatsource aktif.\n"
        dt_bs += f"Kualitas Default: {beatsource_manager.quality}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_bs += f"Cache User (Global): {len([u for u in bot_set.user_data if 'beatsource_qual' in bot_set.user_data[u]])} pengguna\n"
        # --- BATAS PERBAIKAN ---
        dt_bs += f"Cache Langganan: { {k.session.cookie_jar.filter_cookies(k.API_URL).get('sessionid').value[:5]+'...': v for k, v in beatsource_manager.subscription_cache.items()} }"
    else:
        dt_bs += "Tidak ada klien Beatsource yang aktif."
    
    dt_sc = "\n\nSOUNDCLOUD:\n"
    if soundcloud_manager and soundcloud_manager.get_client():
        dt_sc += f"Klien Soundcloud aktif (Token diatur).\n"
        dt_sc += f"Kualitas Default: {soundcloud_manager.quality}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_sc += f"Cache User (Global): {len([u for u in bot_set.user_data if 'soundcloud_qual' in bot_set.user_data[u]])} pengguna"
        # --- BATAS PERBAIKAN ---
    else:
        dt_sc += "Tidak ada klien Soundcloud yang aktif (Token hilang)."

    dt_dz = "\n\nDEEZER:\n"
    if deezer_manager and deezer_manager.clients:
        dt_dz += f"{len(deezer_manager.clients)} klien Deezer aktif.\n"
        dt_dz += f"Kualitas Default: {deezer_manager.quality}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_dz += f"Cache User (Global): {len([u for u in bot_set.user_data if 'deezer_qual' in bot_set.user_data[u]])} pengguna"
        # --- BATAS PERBAIKAN ---
    else:
        dt_dz += "Tidak ada klien Deezer yang aktif."

    dt_td = "\n\nTIDAL:\n"
    if tidal_manager and tidal_manager.clients:
        dt_td += f"{len(tidal_manager.clients)} klien Tidal aktif.\n"
        dt_td += f"Kualitas Default: {tidal_manager.quality}, Spasial: {tidal_manager.spatial}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_td += f"Cache User (Global): {len([u for u in bot_set.user_data if 'tidal_qual' in bot_set.user_data[u]])} pengguna"
        # --- BATAS PERBAIKAN ---
    else:
        dt_td += "Tidak ada klien Tidal yang aktif."

    dt_kk = "\n\nKKBOX:\n"
    if kkbox_manager and kkbox_manager.clients:
        dt_kk += f"{len(kkbox_manager.clients)} klien KKBox aktif.\n"
        dt_kk += f"Kualitas Default: {kkbox_manager.quality}\n"
        # --- PERBAIKAN: Baca dari bot_set ---
        dt_kk += f"Cache User (Global): {len([u for u in bot_set.user_data if 'kkbox_qual' in bot_set.user_data[u]])} pengguna"
        # --- BATAS PERBAIKAN ---
    else:
        dt_kk += "Tidak ada klien KKBox yang aktif."

    # --- TAMBAHAN BARU: Debug Napster ---
    dt_np = "\n\nNAPSTER:\n"
    if napster_manager and napster_manager.clients:
        dt_np += f"{len(napster_manager.clients)} klien Napster aktif.\n"
        dt_np += f"Kualitas Default: {napster_manager.quality}\n"
        dt_np += f"Cache User (Global): {len([u for u in bot_set.user_data if 'napster_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_np += "Tidak ada klien Napster yang aktif."
    # --- BATAS TAMBAHAN ---
    
    # --- TAMBAHAN BARU: Debug Idagio ---
    dt_id = "\n\nIDAGIO:\n"
    if idagio_manager and idagio_manager.clients:
        dt_id += f"{len(idagio_manager.clients)} klien Idagio aktif.\n"
        dt_id += f"Kualitas Default: {idagio_manager.quality}\n"
        dt_id += f"Cache User (Global): {len([u for u in bot_set.user_data if 'idagio_qual' in bot_set.user_data[u]])} pengguna"
    else:
        dt_id += "Tidak ada klien Idagio yang aktif."
    # --- BATAS TAMBAHAN ---

    zips = f"\n\n{bot_set.album_zip}"
    user_dict = bot_set.user_data
    zips += f"\n\n{user_dict}"
    
    await m.reply(dt_qb + dt_bp + dt_bs + dt_sc + dt_dz + dt_td + dt_kk + dt_np + dt_id + zips, True)
