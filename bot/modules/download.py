# [GANTI FILE: bot/modules/download.py]

from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio 
import traceback
import random

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang

from bot import BOT_QOBUZ_CLIENTS
from bot.tgclient import aio 

# Impor semua manajer
from bot.helpers.deezer.manager import deezer_manager
from bot.helpers.beatport.manager import beatport_manager
from bot.helpers.tidal.manager import tidal_manager
from bot.helpers.kkbox.manager import kkbox_manager
from bot.helpers.beatsource.manager import beatsource_manager
from bot.helpers.soundcloud.manager import soundcloud_manager
# --- TAMBAHAN BARU: Impor Manajer Napster ---
try:
    from bot.helpers.napster.manager import napster_manager
except ImportError:
    napster_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Idagio ---
try:
    from bot.helpers.idagio.manager import idagio_manager
except ImportError:
    idagio_manager = None
# --- BATAS TAMBAHAN ---

from ..helpers.soundcloud.handler import start_soundcloud
from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.beatport.handler import start_beatport

try:
    from ..helpers.kkbox.handler import start_kkbox
except ImportError:
    async def start_kkbox(*args, **kwargs):
        raise NotImplementedError("Modul KKBox ('handler.py') belum diimplementasikan.")
        
try:
    from ..helpers.beatsource.handler import start_beatsource
except ImportError:
    async def start_beatsource(*args, **kwargs):
        raise NotImplementedError("Modul Beatsource ('handler.py') belum diimplementasikan.")

# --- TAMBAHAN BARU: Impor Handler Napster ---
try:
    from ..helpers.napster.handler import start_napster
except ImportError:
    async def start_napster(*args, **kwargs):
        raise NotImplementedError("Modul Napster ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler Idagio ---
try:
    from ..helpers.idagio.handler import start_idagio
except ImportError:
    async def start_idagio(*args, **kwargs):
        raise NotImplementedError("Modul Idagio ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

from ..helpers.message import send_message, check_user, fetch_user_details, edit_message


async def run_download_task(link: str, user: dict):
    """
    Fungsi ini berjalan di latar belakang.
    Ia menangani seluruh siklus hidup tugas: mulai, error, cleanup.
    """
    
    task_successful = False
    
    try:
        user['bot_msg'] = await send_message(user, 'Memulai tugas...')
        
        await start_link(link, user)
        
        task_successful = True 
        
    except asyncio.CancelledError:
        LOGGER.info(f"Tugas untuk {user['user_id']} dibatalkan (mungkin shutdown).")
        await send_message(user, "Tugas dibatalkan.")
        await asyncio.sleep(5) 
            
    except Exception as e:
        error_message = f"Tugas Gagal: Terjadi error.\n`{e}`"
        if "not available in any" in str(e) or "Maaf, tidak ada akun" in str(e) or "NotImplementedError" in str(e) or "URL Deezer tidak valid" in str(e):
            error_message = f"Tugas Gagal: {e}"
            
        LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")
        try:
            await edit_message(user['bot_msg'], error_message)
        except:
            pass 
            
    finally:
        await cleanup(user) # Hapus file
        
        try:
            if task_successful:
                await aio.delete_messages(user['chat_id'], user['bot_msg'].id)
        except:
            pass


@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg:Message):
    if await check_user(msg=msg):
        
        text_content = ""
        reply = False
        
        if msg.reply_to_message:
            text_content = msg.reply_to_message.text
            reply = True
        else:
            text_content = msg.text
            reply = False

        link = ""
        try:
            parts = text_content.split()
            for part in parts:
                if part.startswith("http://") or part.startswith("https://"):
                    link = part 
                    break 

            if not link:
                raise IndexError
                
        except IndexError:
            return await send_message(msg, lang.s.ERR_NO_LINK)

        if not link:
            return await send_message(msg, lang.s.ERR_LINK_RECOGNITION)
        
        user = await fetch_user_details(msg, reply)
        user['link'] = link
        
        asyncio.create_task(run_download_task(link, user))


async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    beatport = ["https://www.beatport.com", "beatport.com"]
    beatsource = ["https://www.beatsource.com", "beatsource.com"]
    
    soundcloud = [
        "https://soundcloud.com", "soundcloud.com", 
        "https://on.soundcloud.com", "on.soundcloud.com",
        "https://m.soundcloud.com", "m.soundcloud.com"
    ]
    
    kkbox = ["https://play.kkbox.com", "https://www.kkbox.com", "kkbox.com"]
    
    # --- TAMBAHAN BARU: URL Napster ---
    napster = ["https://app.napster.com", "napster.com", "http://app.napster.com"]
    # --- BATAS TAMBAHAN ---
    
    # --- TAMBAHAN BARU: URL Idagio ---
    idagio = ["https://www.idagio.com", "idagio.com", "https://app.idagio.com"]
    # --- BATAS TAMBAHAN ---
    
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        
        if not tidal_manager.clients:
            raise Exception("Maaf, tidak ada akun Tidal bot yang aktif saat ini.")

        clients_list = list(tidal_manager.clients)
        if len(clients_list) > 1:
            random.shuffle(clients_list)
        last_error = None
        for client in clients_list:
            try:
                user['tidal_api'] = client
                await start_tidal(link, user)
                LOGGER.info(f"Tidal: Unduhan berhasil menggunakan akun User ID {client.user_id}")
                return
            except Exception as e:
                error_str = str(e).lower()
                if 'asset is not ready' in error_str or \
                   'not available in your region' in error_str or \
                   'region-locked' in error_str:
                    LOGGER.warning(f"Tidal: Akun {client.user_id} gagal (Region Lock): {e}. Mencoba akun berikutnya...")
                    last_error = e
                    continue
                else:
                    LOGGER.error(f"Tidal: Akun {client.user_id} gagal (Fatal): {e}")
                    raise e
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Tidal yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Tidal karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        
        if not deezer_manager.clients:
            raise Exception("Maaf, tidak ada akun Deezer bot yang aktif saat ini.")
        
        clients_list = random.sample(deezer_manager.clients, len(deezer_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['deezer_api'] = client 
                await start_deezer(link, user)
                LOGGER.info(f"Deezer: Unduhan berhasil menggunakan ARL ID {client.user['USER']['USER_ID']}")
                return 
            except Exception as e:
                error_str = str(e).lower()
                # --- PERBAIKAN: Hapus "url deezer tidak valid" ---
                # Biarkan error "URL tidak valid" menjadi fatal dan menghentikan tugas.
                if "not available in your country" in error_str or \
                   "not available by your subscription" in error_str or \
                   "track not available" in error_str:
                # --- AKHIR PERBAIKAN ---
                    LOGGER.warning(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Region/Sub Lock): {e}. Mencoba ARL berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Fatal): {e}")
                    raise e # Lempar error (seperti "URL tidak valid") sebagai fatal
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Deezer yang dicoba. Error terakhir: {last_error}")
        else:
            # Jika loop selesai tanpa 'return', tetapi 'last_error' tidak ada,
            # itu berarti 'raise e' terakhir (error fatal) seharusnya terlempar.
            # Bagian ini seharusnya tidak tercapai jika ada error fatal.
            raise Exception("Gagal mengunduh Deezer karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list
        await start_qobuz(link, user)

    elif link.startswith(tuple(beatport)):
        user['provider'] = 'Beatport'
        
        if not beatport_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatport bot yang aktif saat ini.")

        clients_list = random.sample(beatport_manager.clients, len(beatport_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['beatport_api'] = client 
                await start_beatport(link, user)
                LOGGER.info(f"Beatport: Unduhan berhasil menggunakan akun.") 
                return 
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str:
                    LOGGER.warning(f"Beatport: Akun gagal (Region/Sub Lock/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatport: Akun gagal (Fatal): {e}")
                    raise e 
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatport yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatport karena alasan yang tidak diketahui setelah mencoba semua akun.")

    elif link.startswith(tuple(beatsource)):
        user['provider'] = 'Beatsource'
        
        if not beatsource_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatsource bot yang aktif saat ini.")

        clients_list = random.sample(beatsource_manager.clients, len(beatsource_manager.clients))
        last_error = None

        for client in clients_list:
            try:
                user['beatsource_api'] = client 
                await start_beatsource(link, user)
                
                LOGGER.info(f"Beatsource: Unduhan berhasil menggunakan akun.") 
                return 
                
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str or \
                   "login gagal" in error_str:
                    LOGGER.warning(f"Beatsource: Akun gagal (Region/Sub Lock/Auth/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatsource: Akun gagal (Fatal): {e}")
                    raise e 
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatsource yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatsource karena alasan yang tidak diketahui setelah mencoba semua akun.")
    
    elif link.startswith(tuple(soundcloud)):
        user['provider'] = 'Soundcloud'
        
        client = soundcloud_manager.get_client()
        if not client:
            raise Exception("Maaf, modul Soundcloud bot tidak aktif saat ini (Token salah atau hilang).")

        try:
            user['soundcloud_api'] = client
            await start_soundcloud(link, user)
            LOGGER.info(f"Soundcloud: Unduhan berhasil.") 
            return 
            
        except Exception as e:
            LOGGER.error(f"Soundcloud: Tugas gagal (Fatal): {e}")
            raise e 
    
    elif link.startswith(tuple(kkbox)):
        user['provider'] = 'KKBox'
        
        if not kkbox_manager.clients:
            raise Exception("Maaf, tidak ada akun KKBox bot yang aktif saat ini.")

        clients_list = random.sample(kkbox_manager.clients, len(kkbox_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['kkbox_api'] = client
                await start_kkbox(link, user)
                LOGGER.info(f"KKBox: Unduhan berhasil menggunakan akun.") 
                return
            except Exception as e:
                error_str = str(e).lower()
                if "unsupported region" in error_str or \
                   "account expired" in error_str or \
                   "quality not available" in error_str or \
                   "incorrect password" in error_str or \
                   "email not found" in error_str:
                    LOGGER.warning(f"KKBox: Akun gagal (Region/Sub/Auth): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue
                else:
                    LOGGER.error(f"KKBox: Akun gagal (Fatal): {e}")
                    raise e
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun KKBox yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh KKBox karena alasan yang tidak diketahui setelah mencoba semua akun.")

    # --- TAMBAHAN BARU: Blok Napster ---
    elif link.startswith(tuple(napster)):
        user['provider'] = 'Napster'
        
        if not napster_manager or not napster_manager.clients:
            raise Exception("Maaf, tidak ada akun Napster bot yang aktif saat ini.")

        client = napster_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Napster yang tersedia (semua gagal login?).")

        try:
            user['napster_api'] = client
            await start_napster(link, user)
            LOGGER.info(f"Napster: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            # Napster API tampaknya tidak terlalu rentan region-lock,
            # tapi Anda bisa menambahkan logika 'try/except' di sini jika perlu.
            LOGGER.error(f"Napster: Tugas gagal (Fatal): {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Idagio ---
    elif link.startswith(tuple(idagio)):
        user['provider'] = 'Idagio'
        
        if not idagio_manager or not idagio_manager.clients:
            raise Exception("Maaf, tidak ada akun Idagio bot yang aktif saat ini.")

        client = idagio_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Idagio yang tersedia (semua gagal login?).")

        try:
            user['idagio_api'] = client
            await start_idagio(link, user)
            LOGGER.info(f"Idagio: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Idagio: Tugas gagal (Fatal): {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    else:
        LOGGER.warning(f"Link tidak dikenali: {link}")
        raise Exception(f"Link tidak dikenali. Bot tidak tahu cara mengunduh dari: {link}")
