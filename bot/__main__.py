# [GANTI FILE: bot/__main__.py]

import os
import signal
import asyncio, sys, logging, traceback

from bot import Config

from .tgclient import aio
from .settings import bot_set

# --- Blok Impor Qobuz ---
try:
    from .helpers.qobuz.qopy import QoClient
except ImportError:
    logging.critical("Gagal mengimpor QoClient! Pastikan path 'from .helpers.qobuz.qopy import QoClient' benar.")
    sys.exit(1)
from bot import BOT_QOBUZ_CLIENTS
try:
    from .helpers.database.mongo_async import database
except ImportError:
    logging.critical("Gagal mengimpor 'database' dari .helpers.database.mongo_async!")
    sys.exit(1)
# --- Batas Blok Impor Qobuz ---


# --- Impor Manajer Deezer ---
try:
    from .helpers.deezer.manager import deezer_manager
except ImportError:
    logging.critical("Gagal mengimpor 'deezer_manager'!")
    sys.exit(1)

# --- Impor Manajer Beatport ---
try:
    from .helpers.beatport.manager import beatport_manager
except ImportError:
    logging.critical("Gagal mengimpor 'beatport_manager'!")
    sys.exit(1)
# --- Batas Impor ---

# --- MODIFIKASI: Impor Manajer Tidal ---
try:
    from .helpers.tidal.manager import tidal_manager
except ImportError:
    logging.critical("Gagal mengimpor 'tidal_manager'!")
    sys.exit(1)
# --- MODIFIKASI SELESAI ---


# --- Fungsi Login Qobuz (Milik Anda, Tetap Sama) ---
async def login_single_client(creds: dict):
    """
    Helper untuk meloginkan satu klien, memuat pengaturannya dari DB,
    dan menyimpannya ke dictionary global.
    """
    creds_copy = creds.copy()
    account_id = creds_copy.pop("id")
    
    client = QoClient(**creds_copy) 
    
    try:
        # 1. Login Klien
        await client.login()
        
        # 2. Muat Kualitas Default Bot dari DB
        try:
            # --- PERBAIKAN QOBUZ: Gunakan filter yang benar ---
            db_settings_doc = await database.get_variable({"key": "QOBUZ_QUALITY"})
            db_default_q = db_settings_doc.get("value") if db_settings_doc else None
            # --- PERBAIKAN SELESAI ---
            client.quality = int(db_default_q) if db_default_q else 6 # Default 6 (Lossless) jika tidak ada
            logging.debug(f"Berhasil memuat Kualitas Default Qobuz '{client.quality}' untuk Akun #{account_id}.")
        except Exception as e:
            logging.error(f"Gagal memuat Kualitas Default Qobuz dari DB untuk Akun #{account_id}: {e}. Menggunakan default 6.")
            client.quality = 6

        # 3. Muat Semua Pengaturan Kualitas Pengguna dari DB
        try:
            logging.debug(f"Memuat pengaturan Qobuz pengguna dari DB untuk Akun #{account_id}...")
            # --- PERBAIKAN QOBUZ: Gunakan database.client ---
            all_users_from_db = await database.client.users.find({}).to_list(None)
            # --- PERBAIKAN SELESAI ---
            
            count = 0
            for user_doc in all_users_from_db:
                user_id = user_doc.get('_id')
                qobuz_qual = user_doc.get('qobuz_qual') 
                
                if user_id and qobuz_qual:
                    await client.setup_quality(user_id, int(qobuz_qual))
                    count += 1
            logging.debug(f"Berhasil memuat {count} pengaturan Qobuz pengguna untuk Akun #{account_id}.")
        except Exception as e:
            logging.error(f"Gagal memuat pengaturan Qobuz pengguna dari DB: {e}")
            logging.warning("Pengaturan kualitas pengguna mungkin tidak akan persisten.")

        # 4. Simpan klien yang SUDAH LOGIN & DIKONFIGURASI ke dictionary global
        BOT_QOBUZ_CLIENTS[account_id] = client
        logging.debug(f"Berhasil login & konfigurasi Akun Qobuz #{account_id} (Label: {client.label})")
        
    except Exception as e:
        logging.error(f"Gagal login utama Akun Qobuz #{account_id}: {e}")
        await client.close_session()


async def load_all_bot_qobuz_clients():
    """
    Me-loop Config.QOBUZ_ACCOUNTS dan meloginkan semuanya
    saat bot startup.
    """
    logging.info(f"Memuat {len(Config.QOBUZ_ACCOUNTS)} akun Qobuz dari config...")
    
    tasks = []
    for account_creds in Config.QOBUZ_ACCOUNTS:
        tasks.append(login_single_client(account_creds))
        
    await asyncio.gather(*tasks)
    
    if not BOT_QOBUZ_CLIENTS:
        logging.warning("PERINGATAN: Tidak ada akun Qobuz bot yang berhasil login! Fungsi Qobuz tidak akan bekerja.")
    else:
        logging.info(f"Berhasil login total {len(BOT_QOBUZ_CLIENTS)} akun Qobuz.")
# --- Batas Fungsi Login Qobuz ---


def signal_handler(s, f):
    try:
        logging.info("Signal received! Exiting....")
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)


async def main():
    await bot_set.set_language()
    
    # 1. Login Qobuz
    await load_all_bot_qobuz_clients()

    # 2. Login Deezer
    logging.info("Memulai inisialisasi Manajer Deezer...")
    await deezer_manager.initialize_clients()
    if deezer_manager.clients: 
        bot_set.deezer = True 
        logging.info(f"Manajer Deezer berhasil diinisialisasi dengan {len(deezer_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Deezer yang berhasil login!")

    # 3. Login Beatport
    logging.info("Memulai inisialisasi Manajer Beatport...")
    await beatport_manager.initialize_clients()
    if beatport_manager.clients:
        # Tambahkan 'self.beatport = False' di settings.py agar ini berfungsi
        bot_set.beatport = True 
        logging.info(f"Manajer Beatport berhasil diinisialisasi dengan {len(beatport_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Beatport yang berhasil login!")

    # --- MODIFIKASI: Ganti 'bot_set.login_tidal()' ---
    # 4. Login Tidal
    logging.info("Memulai inisialisasi Manajer Tidal...")
    await tidal_manager.initialize_clients()
    if tidal_manager.clients:
        logging.info(f"Manajer Tidal berhasil diinisialisasi dengan {len(tidal_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Tidal yang berhasil login! (Gunakan /settings untuk login)")
    # --- MODIFIKASI SELESAI ---

    logging.info("Menginisialisasi data pengguna...")
    await bot_set.initialize_users()

    await aio.start()
    signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(main())
        loop.run_forever()
    except Exception:
        logging.error(traceback.format_exc())
        sys.exit(1)
