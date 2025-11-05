# [GANTI FILE: bot/modules/provider_settings.py]

import bot.helpers.translations as lang

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config

from ..logger import LOGGER
from ..settings import bot_set
from ..helpers.buttons.settings import *
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import tidalapi
from ..helpers.message import edit_message, check_user

from bot import BOT_QOBUZ_CLIENTS
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatport_manager. Panel Beatport tidak akan berfungsi.")
    beatport_manager = None
# --- MODIFIKASI DIMULAI ---
try:
    from ..helpers.deezer.manager import deezer_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor deezer_manager. Panel Deezer tidak akan berfungsi.")
    deezer_manager = None
# --- MODIFIKASI SELESAI ---


@Client.on_callback_query(filters.regex(pattern=r"^providerPanel"))
async def provider_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.PROVIDERS_PANEL,
            providers_button()
        )


#----------------
# QOBUZ
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^qbP"))
async def qobuz_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
        
        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(cb.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        
        client_to_check = list(BOT_QOBUZ_CLIENTS.values())[0]
        current = client_to_check.quality
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(
            cb.message,
            lang.s.QOBUZ_QUALITY_PANEL,
            markup=qb_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^qbQ"))
async def qobuz_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qobuz = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
        to_set = cb.data.split('_')[1]
        qobuz_qual = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]

        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(cb.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        
        for client in BOT_QOBUZ_CLIENTS.values():
            client.quality = qobuz_qual

        await database.set_variable('QOBUZ_QUALITY', qobuz_qual)
        
        await qobuz_cb(c, cb)


#----------------
# TIDAL
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^tdP"))
async def tidal_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_buttons() 
        )
    
@Client.on_callback_query(filters.regex(pattern=r"^tdQ"))
async def tidal_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qualities = {
            'LOW': 'LOW',
            'HIGH': 'HIGH',
            'LOSSLESS': 'LOSSLESS'
        }
        if tidalapi.mobile_hires:
            qualities['HI_RES'] = 'MAX'
        qualities[tidalapi.quality] += '✅'

        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_quality_button(qualities)
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdSQ"))
async def tidal_set_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
  
        if to_set == 'spatial':
            options = ['OFF', 'ATMOS AC3 JOC']
            if tidalapi.mobile_atmos:
                options.append('ATMOS AC4')
            if tidalapi.mobile_atmos or tidalapi.mobile_hires:
                options.append('Sony 360RA')

            try:
                current = options.index(tidalapi.spatial)
            except:
                current = 0
                
            nexti = (current + 1) % len(options) # Diperbaiki agar lebih dinamis
            tidalapi.spatial = options[nexti]
            await database.set_variable('TIDAL_SPATIAL', options[nexti])
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            tidalapi.quality = to_set
            await database.set_variable('TIDAL_QUALITY', to_set)
            
        await tidal_quality_cb(c, cb)

# ... (tidal_auth_cb, tidal_login_cb, tidal_remove_login_cb tetap sama) ...
@Client.on_callback_query(filters.regex(pattern=r"^tdAuth"))
async def tidal_auth_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        sub = tidalapi.sub_type
        hires = True if tidalapi.mobile_hires else False
        atmos = True if tidalapi.mobile_atmos else False
        tv = True if tidalapi.tv_session else False

        await edit_message(
            cb.message,
            lang.s.TIDAL_AUTH_PANEL.format(sub, hires, atmos, tv),
            tidal_auth_buttons()
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdLogin"))
async def tidal_login_cb(c:Client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        auth_url, err = await tidalapi.get_tv_login_url()
        if err:
            return await c.answer_callback_query(cb.id, err, True)
    
        await edit_message(cb.message, lang.s.TIDAL_AUTH_URL.format(auth_url), tidal_auth_buttons())

        sub, err = await tidalapi.login_tv()
        if err:
            return await edit_message(cb.message, lang.s.ERR_LOGIN_TIDAL_TV_FAILED.format(err), tidal_auth_buttons())
        if sub:
            bot_set.tidal = tidalapi
            bot_set.clients.append(tidalapi)
            await bot_set.save_tidal_login(tidalapi.tv_session)
            hires = True if tidalapi.mobile_hires else False
            atmos = True if tidalapi.mobile_atmos else False
            tv = True if tidalapi.tv_session else False
            await edit_message(cb.message, lang.s.TIDAL_AUTH_PANEL.format(sub, hires, atmos, tv) + '\n' + lang.s.TIDAL_AUTH_SUCCESSFULL, tidal_auth_buttons())

@Client.on_callback_query(filters.regex(pattern=r"^tdRemove"))
async def tidal_remove_login_cb(c: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await database.set_variable("TIDAL_AUTH_DATA", None)
        tidalapi.tv_session = None
        tidalapi.mobile_atmos = None
        tidalapi.mobile_hires = None
        tidalapi.sub_type = None
        tidalapi.saved = []
        if hasattr(tidalapi, "session"):
            await tidalapi.session.close()
        bot_set.tidal = None
        await c.answer_callback_query(cb.id, lang.s.TIDAL_REMOVED_SESSION, True)
        await tidal_auth_cb(c, cb)

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
            markup=bp_button(quality) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^bpQ"))
async def beatport_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
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
        
        beatport_manager.quality = to_set
        await database.set_variable('BEATPORT_QUALITY', to_set)
        
        await beatport_cb(c, cb)


# --- FUNGSI BARU DIMULAI ---
#----------------
# DEEZER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^dzP"))
async def deezer_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "MP3 320",
            "MP3_128": "MP3 128"
        }
        
        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(cb.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")
        
        current = deezer_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Deezer:",
            markup=dz_button(quality) # Menggunakan dz_button (mode admin)
        )

@Client.on_callback_query(filters.regex(pattern=r"^dzQ"))
async def deezer_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "FLAC": "FLAC",
            "MP3 320": "MP3_320",
            "MP3 128": "MP3_128"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)

        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(cb.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")
        
        deezer_manager.quality = to_set
        await database.set_variable('DEEZER_QUALITY', to_set)
        
        await deezer_cb(c, cb)
# --- FUNGSI BARU SELESAI ---
