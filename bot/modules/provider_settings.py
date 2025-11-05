# [GANTI FILE: bot/modules/provider_settings.py]

import bot.helpers.translations as lang
import traceback # <-- Ditambahkan

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config

from ..logger import LOGGER
from ..settings import bot_set
from ..helpers.buttons.settings import *
from ..helpers.database.mongo_async import database
# --- MODIFIKASI: Impor kelas, bukan instans ---
from ..helpers.tidal.tidal_api import TidalApi
# --- MODIFIKASI SELESAI ---
from ..helpers.message import edit_message, check_user

from bot import BOT_QOBUZ_CLIENTS
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatport_manager.")
    beatport_manager = None
# --- MODIFIKASI DIMULAI ---
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
# --- MODIFIKASI SELESAI ---


@Client.on_callback_query(filters.regex(pattern=r"^providerPanel"))
async def provider_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.PROVIDERS_PANEL,
            providers_button()
        )

# ... (Fungsi Qobuz tetap sama) ...
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
# TIDAL (DIREFAKTOR)
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^tdP"))
async def tidal_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_buttons() # auth and quality button (quality button only if auth already done)
        )
    
@Client.on_callback_query(filters.regex(pattern=r"^tdQ"))
async def tidal_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qualities = {
            'LOW': 'LOW',
            'HIGH': 'HIGH',
            'LOSSLESS': 'LOSSLESS'
        }
        # --- MODIFIKASI: Gunakan manager ---
        if any(c.mobile_hires for c in tidal_manager.clients):
            qualities['HI_RES'] = 'MAX'
        qualities[tidal_manager.quality] += '✅'

        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_quality_button(qualities, spatial=tidal_manager.spatial) # Teruskan spatial default
        )
        # --- MODIFIKASI SELESAI ---


@Client.on_callback_query(filters.regex(pattern=r"^tdSQ"))
async def tidal_set_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
  
        if to_set == 'spatial':
            options = ['OFF', 'ATMOS AC3 JOC']
            # --- MODIFIKASI: Gunakan manager ---
            if any(c.mobile_atmos for c in tidal_manager.clients):
                options.append('ATMOS AC4')
            if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients):
                options.append('Sony 360RA')

            try:
                current = options.index(tidal_manager.spatial)
            except:
                current = 0
                
            nexti = (current + 1) % len(options) # Diperbaiki
            tidal_manager.spatial = options[nexti]
            await database.set_variable('TIDAL_SPATIAL', options[nexti])
            # --- MODIFIKASI SELESAI ---
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            # --- MODIFIKASI: Gunakan manager ---
            tidal_manager.quality = to_set
            await database.set_variable('TIDAL_QUALITY', to_set)
            # --- MODIFIKASI SELESAI ---
            
        await tidal_quality_cb(c, cb)


@Client.on_callback_query(filters.regex(pattern=r"^tdAuth"))
async def tidal_auth_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # --- MODIFIKASI: Tampilkan status multi-akun ---
        text = f"{len(tidal_manager.clients)} akun Tidal terhubung.\n\n"
        
        for i, client in enumerate(tidal_manager.clients):
            sub_type = client.sub_type or "Unknown"
            text += f"  **Akun {i+1} (User {client.user_id})**\n"
            text += f"  > Tipe: {sub_type}\n"
            text += f"  > Hires: {bool(client.mobile_hires)}, Atmos: {bool(client.mobile_atmos)}\n"
        
        text += "\nGunakan tombol di bawah untuk menambah akun baru (via TV) atau menghapus *semua* akun."

        await edit_message(
            cb.message,
            text,
            tidal_auth_buttons()
        )
        # --- MODIFIKASI SELESAI ---

@Client.on_callback_query(filters.regex(pattern=r"^tdLogin"))
async def tidal_login_cb(c:Client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        
        # --- MODIFIKASI: Alur login multi-akun ---
        temp_client = TidalApi() # Buat instans sementara
        
        try:
            auth_url, err = await temp_client.get_tv_login_url()
            if err:
                return await c.answer_callback_query(cb.id, err, True)
        
            await edit_message(
                cb.message,
                lang.s.TIDAL_AUTH_URL.format(auth_url),
                tidal_auth_buttons()
            )

            sub, err = await temp_client.login_tv()
            if err:
                return await edit_message(
                    cb.message,
                    lang.s.ERR_LOGIN_TIDAL_TV_FAILED.format(err),
                    tidal_auth_buttons()
                )
            
            if sub:
                # Dapatkan data auth untuk disimpan
                auth_data = {
                    'refresh_token': temp_client.tv_session.refresh_token,
                    'country_code': temp_client.tv_session.country_code,
                    'user_id': temp_client.tv_session.user_id
                }
                
                # Ambil daftar akun yang ada dari DB
                accounts_list_doc = await database.get_variable({"key": "TIDAL_ACCOUNTS_LIST"})
                accounts_list = accounts_list_doc.get("value", []) if accounts_list_doc else []
                
                # Tambahkan akun baru
                accounts_list.append(auth_data)
                
                # Simpan daftar baru ke DB
                await database.set_variable('TIDAL_ACCOUNTS_LIST', accounts_list)
                
                # Inisialisasi ulang manajer
                await tidal_manager.initialize_clients()
                
                await temp_client.session.close() # Tutup sesi sementara

                await edit_message(
                    cb.message,
                    f"Akun {sub} (User {auth_data['user_id']}) berhasil ditambahkan.\n"
                    f"Total akun: {len(tidal_manager.clients)}",
                    tidal_auth_buttons()
                )
        except Exception as e:
            LOGGER.error(f"Gagal login Tidal: {traceback.format_exc()}")
            await temp_client.session.close() # Pastikan sesi ditutup
            await c.answer_callback_query(cb.id, f"Error: {e}", True)
        # --- MODIFIKASI SELESAI ---

@Client.on_callback_query(filters.regex(pattern=r"^tdRemove"))
async def tidal_remove_login_cb(c: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # --- MODIFIKASI: Hapus SEMUA akun ---
        # Tutup semua sesi klien yang ada
        for client in tidal_manager.clients:
            if hasattr(client, "session"):
                await client.session.close()
        
        # Hapus daftar akun dari DB
        await database.set_variable("TIDAL_ACCOUNTS_LIST", [])
        
        # Inisialisasi ulang manajer (akan menjadi kosong)
        await tidal_manager.initialize_clients()

        await c.answer_callback_query(
            cb.id,
            "Semua akun Tidal telah dihapus.",
            True
        )

        await tidal_auth_cb(c, cb)
        # --- MODIFIKASI SELESAI ---


# ... (Fungsi Beatport tetap sama) ...
@Client.on_callback_query(filters.regex(pattern=r"^bpP"))
async def beatport_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {"lossless": "Lossless (FLAC)", "high": "High (AAC 256)", "medium": "Medium (AAC 128)"}
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        current = beatport_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, "Pilih kualitas default untuk Beatport:", markup=bp_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^bpQ"))
async def beatport_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {"Lossless (FLAC)": "lossless", "High (AAC 256)": "high", "Medium (AAC 128)": "medium"}
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        beatport_manager.quality = to_set
        await database.set_variable('BEATPORT_QUALITY', to_set)
        await beatport_cb(c, cb)


# --- FUNGSI BARU: Deezer ---
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
