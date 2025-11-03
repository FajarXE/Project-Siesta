# [GANTI FILE: bot/modules/download.py]

from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio 
import traceback
import random

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang

# --- MODIFIKASI: Hapus impor ACTIVE_DOWNLOAD_TASKS ---
from bot import BOT_QOBUZ_CLIENTS
from bot.tgclient import aio 

# --- MODIFIKASI BARU: Impor manajer Deezer ---
from bot.helpers.deezer.manager import deezer_manager
# --- BATAS MODIFIKASI ---

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
# --- MODIFIKASI: Hapus impor antiSpam ---
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
        # --- MODIFIKASI: Kita akan menangani error "tidak ada akun" di sini ---
        error_message = f"Tugas Gagal: Terjadi error.\n`{e}`"
        # Beri pesan yang lebih baik jika tidak ada klien yang login
        if "Tidak ada akun" in str(e):
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
    
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        await start_tidal(link, user)
        
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        
        # --- MODIFIKASI BARU: Tambahkan Logika Klien Deezer ---
        # 1. Ambil klien dari kumpulan (pool)
        client = deezer_manager.get_client()
        
        # 2. Periksa apakah klien ada
        if not client:
            # Lempar error agar 'run_download_task' bisa menangkapnya
            raise Exception("Maaf, tidak ada akun Deezer bot yang aktif saat ini.")
            
        # 3. LAMPIRKAN klien ke kamus user
        user['deezer_api'] = client
        # --- BATAS MODIFIKASI ---
        
        await start_deezer(link, user) #
        
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list

        await start_qobuz(link, user)
