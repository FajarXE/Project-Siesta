from pyrogram.types import Message
from pyrogram import Client, filters

from bot import CMD
from bot.logger import LOGGER

import bot.helpers.translations as lang
import traceback
import random  # Diperlukan untuk mengacak daftar klien

# Impor dictionary klien Qobuz yang aktif
from bot import BOT_QOBUZ_CLIENTS

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.message import send_message, antiSpam, check_user, fetch_user_details


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
        
        spam = await antiSpam(msg.from_user.id, msg.chat.id)
        if not spam:
            user = await fetch_user_details(msg, reply)
            user['link'] = link
            user['bot_msg'] = await send_message(msg, 'Downloading.......')
            try:
                await start_link(link, user)
                # Pesan sukses sekarang akan dikirim dari dalam 'handler.py'
                # await send_message(user, lang.s.TASK_COMPLETED)
            except Exception:
                LOGGER.error(traceback.format_exc())
            
            # Jangan hapus pesan 'bot_msg' di sini, biarkan handler yang mengaturnya
            # await c.delete_messages(msg.chat.id, user['bot_msg'].id)
            await cleanup(user) # deletes uploaded files
            await antiSpam(msg.from_user.id, msg.chat.id, True)

async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    
    if link.startswith(tuple(tidal)):
        await start_tidal(link, user)
    elif link.startswith(tuple(deezer)):
        await start_deezer(link, user)
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        # --- MODIFIKASI DIMULAI (LOGIKA FALLBACK) ---
        if not BOT_QOBUZ_CLIENTS:
            await send_message(user, "Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
            return

        # 1. Ambil SEMUA klien yang aktif
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        
        # 2. Acak daftarnya agar tidak selalu mencoba Akun #1 terlebih dahulu
        random.shuffle(clients_list)
        
        # 3. Masukkan SELURUH DAFTAR klien ke kamus 'user'
        user['qobuz_clients_list'] = clients_list
        # --- MODIFIKASI SELESAI ---

        await start_qobuz(link, user)
