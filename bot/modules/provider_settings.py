# [GANTI FILE: bot/modules/provider_settings.py]

import bot.helpers.translations as lang
import traceback 

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config

from ..logger import LOGGER
from ..settings import bot_set
from ..helpers.buttons.settings import * # Ini sekarang akan mengimpor bs_button & sc_button juga
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import TidalApi
from ..helpers.message import edit_message, check_user

from bot import BOT_QOBUZ_CLIENTS
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

# --- TAMBAHAN: Impor Manajer Beatsource ---
try:
    from ..helpers.beatsource.manager import beatsource_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatsource_manager.")
    beatsource_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN: Impor Manajer Soundcloud ---
try:
    from ..helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor soundcloud_manager.")
    soundcloud_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Napster ---
try:
    from ..helpers.napster.manager import napster_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor napster_manager.")
    napster_manager = None
# --- BATAS TAMBAHAN ---


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
        await edit_message(cb.message, lang.s.QOBUZ_QUALITY_PANEL, markup=qb_button(quality))

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
        if any(c.mobile_hires for c in tidal_manager.clients):
            qualities['HI_RES'] = 'MAX'
        qualities[tidal_manager.quality] += '✅'

        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_quality_button(qualities, spatial=tidal_manager.spatial) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdSQ"))
async def tidal_set_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        if to_set == 'spatial':
            options = ['OFF', 'ATMOS AC3 JOC']
            if any(c.mobile_atmos for c in tidal_manager.clients):
                options.append('ATMOS AC4')
            if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients):
                options.append('Sony 360RA')
            try:
                current = options.index(tidal_manager.spatial)
            except:
                current = 0
            nexti = (current + 1) % len(options) 
            tidal_manager.spatial = options[nexti]
            await database.set_variable('TIDAL_SPATIAL', options[nexti])
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            tidal_manager.quality = to_set
            await database.set_variable('TIDAL_QUALITY', to_set)
        await tidal_quality_cb(c, cb)

@Client.on_callback_query(filters.regex(pattern=r"^tdAuth"))
async def tidal_auth_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        text = f"{len(tidal_manager.clients)} akun Tidal terhubung.\n\n"
        for i, client in enumerate(tidal_manager.clients):
            sub_type = client.sub_type or "Unknown"
            text += f"  **Akun {i+1} (User {client.user_id})**\n"
            text += f"  > Tipe: {sub_type}\n"
            text += f"  > Hires: {bool(client.mobile_hires)}, Atmos: {bool(client.mobile_atmos)}\n"
        text += "\nGunakan tombol di bawah untuk menambah akun baru (via TV) atau menghapus *semua* akun."
        await edit_message(cb.message, text, tidal_auth_buttons())

@Client.on_callback_query(filters.regex(pattern=r"^tdLogin"))
async def tidal_login_cb(c:Client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        temp_client = TidalApi() 
        try:
            auth_url, err = await temp_client.get_tv_login_url()
            if err:
                return await c.answer_callback_query(cb.id, err, True)
            await edit_message(cb.message, lang.s.TIDAL_AUTH_URL.format(auth_url), tidal_auth_buttons())
            sub, err = await temp_client.login_tv()
            if err:
                return await edit_message(cb.message, lang.s.ERR_LOGIN_TIDAL_TV_FAILED.format(err), tidal_auth_buttons())
            if sub:
                auth_data = {
                    'refresh_token': temp_client.tv_session.refresh_token,
                    'country_code': temp_client.tv_session.country_code,
                    'user_id': temp_client.tv_session.user_id
                }
                all_settings = await database.get_variable()
                if not all_settings:
                    all_settings = {}
                accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
                accounts_list.append(auth_data)
                await database.set_variable('TIDAL_ACCOUNTS_LIST', accounts_list)
                await tidal_manager.initialize_clients()
                await temp_client.session.close() 
                await edit_message(cb.message, f"Akun {sub} (User {auth_data['user_id']}) berhasil ditambahkan.\n"
                                f"Total akun: {len(tidal_manager.clients)}", tidal_auth_buttons())
        except Exception as e:
            LOGGER.error(f"Gagal login Tidal: {traceback.format_exc()}")
            if temp_client.session:
                await temp_client.session.close() 
            await c.answer_callback_query(cb.id, f"Error: {e}", True)

@Client.on_callback_query(filters.regex(pattern=r"^tdRemove"))
async def tidal_remove_login_cb(c: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        for client in tidal_manager.clients:
            if hasattr(client, "session") and client.session:
                await client.session.close()
        await database.set_variable("TIDAL_ACCOUNTS_LIST", [])
        await tidal_manager.initialize_clients()
        await c.answer_callback_query(cb.id, "Semua akun Tidal telah dihapus.", True)
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
        await edit_message(cb.message, "Pilih kualitas default untuk Beatport:", markup=bp_button(quality))

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

# --- TAMBAHAN: Handler Admin Beatsource ---
#----------------
# BEATSOURCE
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bsP")) # Beatsource Panel
async def beatsource_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(cb.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        current = beatsource_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Beatsource:\n(Klien non-Pro akan tetap di 128k)",
            markup=bs_button(quality) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^bsQ")) # Beatsource Quality Set
async def beatsource_quality_cb(c, cb:CallbackQuery):
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
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(cb.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        beatsource_manager.quality = to_set
        await database.set_variable('BEATSOURCE_QUALITY', to_set) # Simpan ke DB
        
        await beatsource_cb(c, cb)
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN: Handler Admin Soundcloud ---
#----------------
# SOUNDCLOUD
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^scP")) # Soundcloud Panel
async def soundcloud_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "original": "Original (Jika Ada)",
            "stream": "Stream (Default AAC/MP3)"
        }
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(cb.message, "Layanan Soundcloud tidak aktif (Token salah/hilang).")
        
        current = soundcloud_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Soundcloud:",
            markup=sc_button(quality) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^scQ")) # Soundcloud Quality Set
async def soundcloud_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "Original (Jika Ada)": "original",
            "Stream (Default AAC/MP3)": "stream"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(cb.message, "Layanan Soundcloud tidak aktif.")
        
        soundcloud_manager.quality = to_set
        await database.set_variable('SOUNDCLOUD_QUALITY', to_set) # Simpan ke DB
        
        await soundcloud_cb(c, cb)
# --- BATAS TAMBAHAN ---

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
        await edit_message(cb.message, "Pilih kualitas default untuk Deezer:", markup=dz_button(quality))

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

#----------------
# KKBOX
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^kkbP"))
async def kkbox_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "128k": "MP3 128k",
            "192k": "MP3 192k",
            "320k": "AAC 320k",
            "hifi": "FLAC 16-bit",
            "hires": "FLAC 24-bit"
        }
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(cb.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")
        current = kkbox_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, "Pilih kualitas default untuk KKBox:", markup=kk_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^kkbQ"))
async def kkbox_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "MP3 128k": "128k",
            "MP3 192k": "192k",
            "AAC 320k": "320k",
            "FLAC 16-bit": "hifi",
            "FLAC 24-bit": "hires"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(cb.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")
        kkbox_manager.quality = to_set
        await database.set_variable('KKBOX_QUALITY', to_set)
        await kkbox_cb(c, cb)

# --- TAMBAHAN BARU: Handler Admin Napster ---
#----------------
# NAPSTER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^npP")) # Napster Panel
async def napster_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC (HiRes/Lossless)",
            "MP3_320": "AAC 320k",
            "MP3_192": "AAC 192k",
            "MP3_128": "AAC 128k",
            "MP3_64": "HE-AAC 64k"
        }
        if not napster_manager or not napster_manager.clients:
            return await edit_message(cb.message, "Layanan Napster tidak aktif (tidak ada klien yang login).")
        
        current = napster_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Napster:\n(Kualitas akhir tergantung langganan akun bot)",
            markup=np_button(quality) # Anda perlu membuat np_button
        )

@Client.on_callback_query(filters.regex(pattern=r"^npQ")) # Napster Quality Set
async def napster_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "FLAC (HiRes/Lossless)": "FLAC",
            "AAC 320k": "MP3_320",
            "AAC 192k": "MP3_192",
            "AAC 128k": "MP3_128",
            "HE-AAC 64k": "MP3_64"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not napster_manager or not napster_manager.clients:
            return await edit_message(cb.message, "Layanan Napster tidak aktif.")
        
        napster_manager.quality = to_set
        await database.set_variable('NAPSTER_QUALITY', to_set) # Simpan ke DB
        
        await napster_cb(c, cb)
# --- BATAS TAMBAHAN ---
