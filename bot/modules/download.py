from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio 
import traceback
import random

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang

# --- MODIFIKASI: Impor dictionary task ---
from bot import BOT_QOBUZ_CLIENTS, ACTIVE_DOWNLOAD_TASKS
from bot.tgclient import aio 

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
# --- MODIFIKASI: Menghapus impor antiSpam ---
from ..helpers.message import send_message, check_user, fetch_user_details, edit_message


async def run_download_task(link: str, user: dict):
    """
    Fungsi ini berjalan di latar belakang dan menangani seluruh siklus tugas.
    """
    task_id = user['user_id'] # Dapatkan ID untuk cleanup
    try:
        user['bot_msg'] = await send_message(user, 'Memulai tugas...')
        
        await start_link(link, user)
        
        await asyncio.sleep(5) 
        
    # --- MODIFIKASI: Menangkap pembatalan (Cancellation) ---
    except asyncio.CancelledError:
        LOGGER.info(f"Tugas untuk {task_id} dibatalkan oleh pengguna.")
        # Kita perlu pesan baru karena 'user['bot_msg']' mungkin sudah dihapus
        await send_message(user, "Tugas telah dibatalkan.")
        await asyncio.sleep(5) # Beri waktu pengguna untuk membaca
    # --- BATAS MODIFIKASI ---
            
    except Exception as e:
        LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")
        try:
            await edit_message(user['bot_msg'], f"Tugas Gagal: Terjadi error fatal.\n{e}")
        except:
            pass 
            
    finally:
        await cleanup(user) # Hapus file
        
        # --- MODIFIKASI: Hapus task dari dictionary saat selesai/gagal/dibatalkan ---
        ACTIVE_DOWNLOAD_TASKS.pop(task_id, None)
        # --- BATAS MODIFIKASI ---
        
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
        task_id = user['user_id']

        # --- MODIFIKASI: Mengganti antiSpam dengan cek task aktif ---
        if task_id in ACTIVE_DOWNLOAD_TASKS:
            await send_message(msg, "Anda sudah memiliki unduhan yang sedang berjalan. Kirim /cancel terlebih dahulu untuk membatalkan.")
            return
        # --- BATAS MODIFIKASI ---
        
        # Buat task dan simpan referensinya
        task = asyncio.create_task(run_download_task(link, user))
        ACTIVE_DOWNLOAD_TASKS[task_id] = task
        
        # Kita tidak mengirim balasan "antrian" lagi


async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        await start_tidal(link, user)
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        await start_deezer(link, user)
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list

        await start_qobuz(link, user)
