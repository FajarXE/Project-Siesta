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

# Impor manajer Deezer (sudah ada)
from bot.helpers.deezer.manager import deezer_manager

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
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
        # --- MODIFIKASI: Penanganan error yang lebih baik untuk failover ---
        error_message = f"Tugas Gagal: Terjadi error.\n`{e}`"
        
        # Beri pesan yang lebih jelas jika semua akun gagal
        if "not available in any" in str(e) or "Maaf, tidak ada akun" in str(e):
            error_message = f"Tugas Gagal: {e}"
            
        LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")
        try:
            await edit_message(user['bot_msg'], error_message)
        except:
            pass 
        # --- BATAS MODIFIKASI ---
            
    finally:
        await cleanup(user) 
        
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
        
        # --- MODIFIKASI: Logika Failover Otomatis Deezer ---
        
        # 1. Periksa apakah ada klien yang aktif
        if not deezer_manager.clients:
            raise Exception("Maaf, tidak ada akun Deezer bot yang aktif saat ini.")

        # 2. Ambil *seluruh daftar* klien dan acak urutannya
        clients_list = random.sample(deezer_manager.clients, len(deezer_manager.clients))
        
        last_error = None
        
        # 3. Loop melalui setiap klien
        for client in clients_list:
            try:
                # 4. Lampirkan SATU klien ke kamus user
                # (handler.py sudah dirancang untuk menerima ini)
                user['deezer_api'] = client 
                
                # 5. Coba jalankan seluruh tugas start_deezer
                await start_deezer(link, user)
                
                # 6. Jika berhasil, hentikan loop dan keluar
                LOGGER.info(f"Deezer: Unduhan berhasil menggunakan ARL ID {client.user['USER']['USER_ID']}")
                return 
                
            except Exception as e:
                # 7. Tangkap error spesifik yang terkait dengan ketersediaan
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "not available by your subscription" in error_str or \
                   "track not available" in error_str:
                    
                    LOGGER.warning(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Region/Sub Lock): {e}. Mencoba ARL berikutnya...")
                    last_error = e # Simpan error untuk ditampilkan jika semua gagal
                    continue # Lanjutkan ke ARL berikutnya
                
                else:
                    # 8. Jika ini error fatal (misal 404, 500), segera hentikan
                    LOGGER.error(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Fatal): {e}")
                    raise e # Lempar ulang error fatal
                    
        # 9. Jika loop selesai (semua ARL gagal), lempar error terakhir
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Deezer yang dicoba. Error terakhir: {last_error}")
        else:
            # Ini seharusnya tidak terjadi, tetapi sebagai pengaman
            raise Exception("Gagal mengunduh Deezer karena alasan yang tidak diketahui setelah mencoba semua akun.")
        # --- BATAS MODIFIKASI ---
        
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list

        await start_qobuz(link, user)
