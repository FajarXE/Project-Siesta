# [FILE: bot/modules/provider_settings.py]

import bot.helpers.translations as lang
import traceback 

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config

from ..logger import LOGGER
from ..settings import bot_set
from ..helpers.buttons.settings import *
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import TidalApi
from ..helpers.message import edit_message, check_user

from bot import BOT_QOBUZ_CLIENTS

# --- IMPORT MANAGERS ---
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatport_manager.")
    beatport_manager = None
try:
    from ..helpers.deezer.manager import deezer_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor deezer_manager.")
    deezer_manager = None
try:
    from ..helpers.tidal.manager import tidal_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor tidal_manager.")
    tidal_manager = None
try:
    from ..helpers.kkbox.manager import kkbox_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor kkbox_manager.")
    kkbox_manager = None
try:
    from ..helpers.beatsource.manager import beatsource_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatsource_manager.")
    beatsource_manager = None
try:
    from ..helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor soundcloud_manager.")
    soundcloud_manager = None
try:
    from ..helpers.napster.manager import napster_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor napster_manager.")
    napster_manager = None
try:
    from ..helpers.idagio.manager import idagio_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor idagio_manager.")
    idagio_manager = None
try:
    from ..helpers.bugs.manager import bugs_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor bugs_manager.")
    bugs_manager = None
try:
    from ..helpers.moov.manager import moov_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor moov_manager.")
    moov_manager = None
try:
    from ..helpers.livephish.manager import livephish_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor livephish_manager.")
    livephish_manager = None

#----------------
# QOBUZ
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^qbP"))
async def qobuz_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qualities = {
            "5": "MP3 320",
            "6": "FLAC Lossless",
            "7": "FLAC 24bit/96kHz",
            "27": "FLAC 24bit/192kHz"
        }
        current_q = str(bot_set.qobuz_quality)
        if current_q in qualities:
            qualities[current_q] = qualities[current_q] + "✅"
            
        await edit_message(
            cb.message,
            f"**QOBUZ PANEL**\n\n{len(BOT_QOBUZ_CLIENTS)} Klien Aktif.\n\nKualitas Default:",
            markup=qb_button(qualities)
        )

@Client.on_callback_query(filters.regex(pattern=r"^qbQ"))
async def qobuz_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = int(cb.data.split('_')[1])
        bot_set.qobuz_quality = to_set
        await database.set_variable("QOBUZ_QUALITY", to_set)
        await qobuz_cb(c, cb)

#----------------
# DEEZER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^dzP"))
async def deezer_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "MP3_320",
            "MP3_128": "MP3_128"
        }
        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(cb.message, "Layanan Deezer tidak aktif.")
            
        current = deezer_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message, 
            f"**DEEZER PANEL**\n\n{len(deezer_manager.clients)} ARL Aktif.\n\nKualitas Default:", 
            markup=dz_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^dzQ"))
async def deezer_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        deezer_manager.quality = to_set
        await database.set_variable("DEEZER_QUALITY", to_set)
        await deezer_cb(c, cb)

#----------------
# TIDAL
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^tdP"))
async def tidal_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            "**TIDAL PANEL**",
            markup=tidal_buttons()
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdQ")) 
async def tidal_quality_menu(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qualities = {
            "HI_RES": "HI_RES (Max)",
            "LOSSLESS": "LOSSLESS (High)",
            "HIGH": "HIGH (Low)"
        }
        if not tidal_manager or not tidal_manager.clients:
            return await edit_message(cb.message, "Layanan Tidal tidak aktif.")

        current = tidal_manager.quality
        if current in qualities:
            qualities[current] = qualities[current] + '✅'
            
        current_spatial = "ON" if tidal_manager.spatial else "OFF"
        
        await edit_message(
            cb.message, 
            f"**TIDAL QUALITY**\n\nDefault Quality: {current}\nSpatial Audio: {current_spatial}", 
            markup=tidal_quality_button(qualities, spatial=current_spatial)
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdSQ")) 
async def tidal_quality_set(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        data = cb.data.split('_')
        
        # Cek tombol Spatial
        if len(data) > 1 and data[1] == "spatial":
            tidal_manager.spatial = not tidal_manager.spatial
            # Simpan state spatial
            await database.set_variable("TIDAL_SPATIAL", tidal_manager.spatial)
            return await tidal_quality_menu(c, cb)
            
        to_set = data[1]
        tidal_manager.quality = to_set
        await database.set_variable("TIDAL_QUALITY", to_set)
        await tidal_quality_menu(c, cb)

#----------------
# BEATPORT
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bpP")) 
async def beatport_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC)",
            "medium": "Medium (AAC)"
        }
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif.")
            
        current = beatport_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(cb.message, "**BEATPORT PANEL**", markup=bp_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^bpQ")) 
async def beatport_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        if to_set == "Lossless (FLAC)":
            real_val = "lossless"
        elif to_set == "High (AAC 256)":
            real_val = "high"
        else:
            real_val = "medium"
            
        beatport_manager.quality = real_val
        await database.set_variable("BEATPORT_QUALITY", real_val)
        await beatport_cb(c, cb)

#----------------
# BEATSOURCE
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bsP")) 
async def beatsource_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC)",
            "medium": "Medium (AAC)"
        }
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(cb.message, "Layanan Beatsource tidak aktif.")
        
        current = beatsource_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(cb.message, "**BEATSOURCE PANEL**", markup=bs_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^bsQ")) 
async def beatsource_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        # Mapping dari teks tombol kembali ke value
        if "Lossless" in to_set:
            real_val = "lossless"
        elif "High" in to_set:
            real_val = "high"
        else:
            real_val = "medium"
            
        beatsource_manager.quality = real_val
        await database.set_variable("BEATSOURCE_QUALITY", real_val)
        await beatsource_cb(c, cb)

#----------------
# SOUNDCLOUD
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^scP")) 
async def soundcloud_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "original": "Original",
            "stream": "Stream"
        }
        if not soundcloud_manager:
            return await edit_message(cb.message, "Layanan Soundcloud tidak aktif.")
            
        current = soundcloud_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(cb.message, "**SOUNDCLOUD PANEL**", markup=sc_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^scQ")) 
async def soundcloud_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        data_text = cb.data.split('_')[1]
        if "Original" in data_text:
            real_val = "original"
        else:
            real_val = "stream"
            
        soundcloud_manager.quality = real_val
        await database.set_variable("SOUNDCLOUD_QUALITY", real_val)
        await soundcloud_cb(c, cb)

#----------------
# KKBOX
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^kkbP")) 
async def kkbox_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "hires": "Hi-Res",
            "hifi": "Hi-Fi",
            "320k": "320k",
            "192k": "192k",
            "128k": "128k"
        }
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(cb.message, "Layanan KKBox tidak aktif.")
            
        current = kkbox_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(cb.message, "**KKBOX PANEL**", markup=kk_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^kkbQ")) 
async def kkbox_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # Format tombol: kkbQ_MP3 128k, kkbQ_FLAC 16-bit, dll
        text = cb.data.split('_')[1]
        
        # Mapping balik
        if "Hi-Res" in text or "24-bit" in text: real_val = "hires"
        elif "Hi-Fi" in text or "16-bit" in text: real_val = "hifi"
        elif "320k" in text: real_val = "320k"
        elif "192k" in text: real_val = "192k"
        else: real_val = "128k"
        
        kkbox_manager.quality = real_val
        await database.set_variable("KKBOX_QUALITY", real_val)
        await kkbox_cb(c, cb)

#----------------
# NAPSTER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^npP")) 
async def napster_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "AAC 320",
            "MP3_192": "AAC 192",
            "MP3_128": "AAC 128",
            "MP3_64": "HE-AAC 64"
        }
        if not napster_manager or not napster_manager.clients:
            return await edit_message(cb.message, "Layanan Napster tidak aktif.")
        
        current = napster_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(cb.message, "**NAPSTER PANEL**", markup=np_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^npQ")) 
async def napster_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        text = cb.data.split('_')[1]
        
        # Mapping balik dari text tombol
        if "FLAC" in text: real_val = "FLAC"
        elif "320k" in text: real_val = "MP3_320"
        elif "192k" in text: real_val = "MP3_192"
        elif "128k" in text: real_val = "MP3_128"
        elif "64k" in text: real_val = "MP3_64"
        else: real_val = "MP3_320"
        
        napster_manager.quality = real_val
        await database.set_variable("NAPSTER_QUALITY", real_val)
        await napster_cb(c, cb)

#----------------
# IDAGIO
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^idP")) 
async def idagio_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "AAC 320",
            "MP3_160": "AAC 160"
        }
        if not idagio_manager or not idagio_manager.clients:
            return await edit_message(cb.message, "Layanan Idagio tidak aktif.")
        
        current = idagio_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
            
        await edit_message(cb.message, "**IDAGIO PANEL**", markup=id_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^idQ")) 
async def idagio_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        text = cb.data.split('_')[1]
        if "FLAC" in text: real_val = "FLAC"
        elif "320k" in text: real_val = "MP3_320"
        else: real_val = "MP3_160"
        
        idagio_manager.quality = real_val
        await database.set_variable("IDAGIO_QUALITY", real_val)
        await idagio_cb(c, cb)

#----------------
# BUGS
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bgP")) 
async def bugs_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "flac": "FLAC",
            "aac256": "AAC 320", # Bugs uses slightly different naming
            "320k": "MP3 320",
            "aac": "AAC 128"
        }
        if not bugs_manager or not bugs_manager.clients:
            return await edit_message(cb.message, "Layanan Bugs tidak aktif.")
            
        current = bugs_manager.quality
        # Handling display mark
        # Karena bugs_button pakai mapping sendiri, kita cukup kirim dict apa adanya
        # Tapi tombol butuh tahu mana yang aktif untuk '✅' jika ingin custom
        # Di sini kita modifikasi value di dict untuk display saja
        if current in quality:
            quality[current] += '✅'

        await edit_message(cb.message, "**BUGS PANEL**", markup=bugs_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^bgQ")) 
async def bugs_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        text = cb.data.split('_')[1]
        
        if "FLAC" in text: to_set = "flac"
        elif "AAC 320" in text: to_set = "aac256"
        elif "MP3 320" in text: to_set = "320k"
        else: to_set = "aac"
        
        bugs_manager.quality = to_set
        await database.set_variable("BUGS_QUALITY", to_set)
        
        await bugs_cb(c, cb)


#----------------
# MOOV
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^mvP")) 
async def moov_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "Max (24bit/HR)",
            "MP3_320": "Std (16bit/LL)"
        }
        
        if not moov_manager or not moov_manager.clients:
            return await edit_message(cb.message, "Layanan Moov tidak aktif (tidak ada akun).")
        
        current = moov_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        acc_info = f"{len(moov_manager.clients)} akun aktif."
        
        await edit_message(
            cb.message,
            f"**MOOV PANEL**\n\n{acc_info}\nProxy aktif: {bool(moov_manager.clients[0].proxy)}\n\nPilih kualitas default bot:",
            markup=mv_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^mvQ")) 
async def moov_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        
        moov_manager.quality = to_set
        await database.set_variable("MOOV_QUALITY", to_set)
        await moov_cb(c, cb)

#----------------
# LIVEPHISH
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^lpP")) 
async def livephish_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC (16-bit)",
            "ALAC": "ALAC (16-bit)",
            "AAC": "AAC"
        }
        if not livephish_manager or not livephish_manager.clients:
            return await edit_message(cb.message, "Layanan LivePhish tidak aktif.")
            
        current = livephish_manager.quality
        if current in quality:
            quality[current] += '✅'
            
        await edit_message(cb.message, "**LIVEPHISH PANEL**\nPilih kualitas LivePhish:", markup=lp_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^lpQ")) 
async def livephish_qual_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        livephish_manager.quality = to_set
        await database.set_variable("LIVEPHISH_QUALITY", to_set)
        await livephish_cb(c, cb)
