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
# --- TAMBAHAN: Impor Manajer KKBox ---
from bot.helpers.kkbox.manager import kkbox_manager
# --- BATAS TAMBAHAN ---

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.beatport.handler import start_beatport

# --- TAMBAHAN: Impor Handler KKBox ---
try:
    from ..helpers.kkbox.handler import start_kkbox
except ImportError:
    # Fallback bersih
    async def start_kkbox(*args, **kwargs):
        raise NotImplementedError("Modul KKBox ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

from ..helpers.message import send_message, check_user, fetch_user_details, edit_message


async def run_download_task(link: str, user: dict):
    """
    Fungsi ini berjalan di latar belakang.
    Ia menangani seluruh siklus hidup tugas: mulai, error, cleanup.
    """
    try:
        user['bot_msg'] = await send_message(user, 'Memulai tugas...')
        
        await start_link(link, user)
        
        await asyncio.sleep(5) 
        
    except asyncio.CancelledError:
        LOGGER.info(f"Tugas untuk {user['user_id']} dibatalkan (mungkin shutdown).")
        await send_message(user, "Tugas dibatalkan.")
        await asyncio.sleep(5) 
            
    except Exception as e:
        # Penanganan error yang lebih baik
        error_message = f"Tugas Gagal: Terjadi error.\n`{e}`"
        if "not available in any" in str(e) or "Maaf, tidak ada akun" in str(e) or "NotImplementedError" in str(e):
            error_message = f"Tugas Gagal: {e}"
            
        LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")
        try:
            await edit_message(user['bot_msg'], error_message)
        except:
            pass 
            
    finally:
        await cleanup(user) # Hapus file
        
        try:
            await aio.delete_messages(user['chat_id'], user['bot_msg'].id)
        except:
            pass


@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg:Message):
    if await check_user(msg=msg):
        try:
            if msg.reply_to_message:
                link = msg.reply_to_message.text
                reply = True
            else:
                link = msg.text.split(" ", maxsplit=1)[1]
                reply = False
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
    # --- TAMBAHAN: URL KKBox ---
    kkbox = ["https://play.kkbox.com", "https://www.kkbox.com", "kkbox.com"]
    # --- BATAS TAMBAHAN ---
    
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        
        if not tidal_manager.clients:
            raise Exception("Maaf, tidak ada akun Tidal bot yang aktif saat ini.")

        # ... (Logika retry Tidal tetap sama) ...
        clients_list = list(tidal_manager.clients)
        if len(clients_list) > 1:
            random.shuffle(clients_list)
            
        last_error = None

        for client in clients_list:
            try:
                user['tidal_api'] = client # Injeksi klien
                await start_tidal(link, user) # Panggil handler
                
                LOGGER.info(f"Tidal: Unduhan berhasil menggunakan akun User ID {client.user_id}")
                return # Sukses
                
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
                    raise e # Lempar error fatal
        
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Tidal yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Tidal karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        
        if not deezer_manager.clients:
            raise Exception("Maaf, tidak ada akun Deezer bot yang aktif saat ini.")
        
        # ... (Logika retry Deezer tetap sama) ...
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
                if "not available in your country" in error_str or \
                   "not available by your subscription" in error_str or \
                   "track not available" in error_str:
                    
                    LOGGER.warning(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Region/Sub Lock): {e}. Mencoba ARL berikutnya...")
                    last_error = e 
                    continue 
                
                else:
                    LOGGER.error(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Fatal): {e}")
                    raise e 
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Deezer yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Deezer karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        # ... (Logika Qobuz tetap sama) ...
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list

        await start_qobuz(link, user)

    elif link.startswith(tuple(beatport)):
        user['provider'] = 'Beatport'
        
        if not beatport_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatport bot yang aktif saat ini.")

        # ... (Logika retry Beatport tetap sama) ...
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

    # --- TAMBAHAN: Blok Logika KKBox ---
    elif link.startswith(tuple(kkbox)):
        user['provider'] = 'KKBox'
        
        if not kkbox_manager.clients:
            raise Exception("Maaf, tidak ada akun KKBox bot yang aktif saat ini.")

        clients_list = random.sample(kkbox_manager.clients, len(kkbox_manager.clients))
        last_error = None

        for client in clients_list:
            try:
                user['kkbox_api'] = client # Injeksi klien
                await start_kkbox(link, user) # Panggil handler
                
                LOGGER.info(f"KKBox: Unduhan berhasil menggunakan akun.") 
                return # Sukses
                
            except Exception as e:
                error_str = str(e).lower()
                # Sesuaikan ini dengan string error dari kkapi.py
                if "unsupported region" in error_str or \
                   "account expired" in error_str or \
                   "quality not available" in error_str or \
                   "incorrect password" in error_str or \
                   "email not found" in error_str:
                    LOGGER.warning(f"KKBox: Akun gagal (Region/Sub/Auth): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue # Coba akun berikutnya
                else:
                    # Error fatal yang tidak diketahui
                    LOGGER.error(f"KKBox: Akun gagal (Fatal): {e}")
                    raise e # Hentikan dan laporkan error
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun KKBox yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh KKBox karena alasan yang tidak diketahui setelah mencoba semua akun.")
    # --- BATAS TAMBAHAN ---

