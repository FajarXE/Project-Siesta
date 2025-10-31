from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio  # <-- MODIFIKASI: Ditambahkan

from bot import CMD
from bot.logger import LOGGER

import bot.helpers.translations as lang
import traceback
import random

from bot import BOT_QOBUZ_CLIENTS

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.message import send_message, antiSpam, check_user, fetch_user_details, edit_message


# --- MODIFIKASI DIMULAI (Membuat fungsi 'Wrapper' Latar Belakang) ---
async def run_download_task(link: str, user: dict):
    """
    Fungsi ini berjalan di latar belakang.
    Ia menangani seluruh siklus hidup tugas: mulai, error, cleanup, dan anti-spam.
    """
    try:
        # 1. Buat pesan status yang akan kita update
        user['bot_msg'] = await send_message(user, 'Memulai tugas...')
        
        # 2. Jalankan tugas utama (ini bagian yang lama)
        await start_link(link, user)
        
        # 3. Pesan "Selesai" sekarang ditangani oleh Qobuz/Deezer handler,
        #    tetapi jika mereka gagal, kita perlu membersihkannya.
        #    Kita bisa tambahkan jeda singkat agar pesan "Selesai" terlihat.
        await asyncio.sleep(5) 
        
    except Exception as e:
        # Jika terjadi error fatal yang tidak tertangani, laporkan ke pengguna
        LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")
        try:
            await edit_message(user['bot_msg'], f"Tugas Gagal: Terjadi error fatal.\n{e}")
        except:
            pass # Gagal mengedit pesan
            
    finally:
        # 4. (PENTING) Cleanup dan buka kunci pengguna, bahkan jika error
        await cleanup(user) # deletes uploaded files
        await antiSpam(user['user_id'], user['chat_id'], True)
        
        # 5. Hapus pesan status terakhir (misal: "Selesai" atau "Error")
        try:
            await aio.delete_messages(user['chat_id'], user['bot_msg'].id)
        except:
            pass
# --- MODIFIKASI SELESAI ---


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
        
        # --- MODIFIKASI DIMULAI (Logika Anti-Spam Disederhanakan) ---
        spam = await antiSpam(msg.from_user.id, msg.chat.id)
        if spam:
            # Jika pengguna sudah menjalankan tugas, beri tahu mereka
            await send_message(msg, "Anda sudah memiliki unduhan yang sedang berjalan. Harap tunggu hingga selesai.")
            return
        
        # Jika tidak spam, buat kamus 'user'
        user = await fetch_user_details(msg, reply)
        user['link'] = link
        
        # 1. Jalankan 'run_download_task' di latar belakang
        asyncio.create_task(run_download_task(link, user))
        
        # 2. Segera balas pengguna agar bot tidak "macet"
        await send_message(msg, "✅ Tugas Anda telah ditambahkan ke antrian.")
        # --- MODIFIKASI SELESAI ---


async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    
    if link.startswith(tuple(tidal)):
        await start_tidal(link, user)
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer' # <-- Menambahkan ini untuk konsistensi
        await start_deezer(link, user)
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            # Kita harus melempar (raise) error agar 'run_download_task' bisa menangkapnya
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list

        await start_qobuz(link, user)
