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

# --- Impor Manajer Tidal ---
try:
    from .helpers.tidal.manager import tidal_manager
except ImportError:
    logging.critical("Gagal mengimpor 'tidal_manager'!")
    sys.exit(1)
# --- Batas Impor ---

# --- Impor Manajer KKBox ---
try:
    from .helpers.kkbox.manager import kkbox_manager
except ImportError:
    logging.critical("Gagal mengimpor 'kkbox_manager'!")
    sys.exit(1)
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN: Impor Manajer Beatsource ---
try:
    from .helpers.beatsource.manager import beatsource_manager
except ImportError:
    logging.critical("Gagal mengimpor 'beatsource_manager'!")
    sys.exit(1)
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN: Impor Manajer Soundcloud ---
try:
    from .helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    logging.critical("Gagal mengimpor 'soundcloud_manager'!")
    sys.exit(1)
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Napster ---
try:
    from .helpers.napster.manager import napster_manager
except ImportError:
    logging.critical("Gagal mengimpor 'napster_manager'!")
    napster_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Idagio ---
try:
    from .helpers.idagio.manager import idagio_manager
except ImportError:
    logging.critical("Gagal mengimpor 'idagio_manager'!")
    idagio_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Nugs.net ---
try:
    from .helpers.nugs.manager import nugs_manager
except ImportError:
    logging.critical("Gagal mengimpor 'nugs_manager'!")
    nugs_manager = None
# --- BATAS TAMBAHAN ---


# --- FUNGSI BARU UNTUK MEMUAT PENGATURAN PENGGUNA ---

async def load_all_user_settings_into_managers():
    """
    Menyinkronkan pengaturan dari cache global (bot_set.user_data)
    ke dalam cache RAM manajer lokal (seperti Napster, Deezer, dll.)
    
    Ini diperlukan agar pengaturan tetap ada setelah bot di-restart.
    Qobuz dan Tidal menangani ini secara berbeda dan tidak disertakan di sini.
    """
    logging.info("Menyinkronkan pengaturan pengguna dari bot_set ke cache manajer lokal...")
    try:
        count = 0
        
        # Manajer ini menggunakan cache RAM lokal via setup_quality()
        settings_map = {
            'deezer_qual': deezer_manager,
            'beatport_qual': beatport_manager,
            'kkbox_qual': kkbox_manager,
            'beatsource_qual': beatsource_manager,
            'soundcloud_qual': soundcloud_manager,
            'napster_qual': napster_manager,
            'idagio_qual': idagio_manager,
        }

        # Loop melalui cache global bot_set yang SEKARANG SUDAH DIISI oleh initialize_users()
        for user_id, user_data in bot_set.user_data.items():
            if not user_id:
                continue
            
            for key, manager in settings_map.items():
                quality_val = user_data.get(key)
                # Jika nilai ditemukan di bot_set DAN manajer-nya ada
                if quality_val and manager:
                    try:
                        # Panggil setup_quality untuk mengisi cache lokal manajer
                        await manager.setup_quality(user_id, quality_val)
                        count += 1
                    except Exception as e:
                        logging.error(f"Gagal memuat {key} untuk user {user_id} ke cache manajer: {e}")
        
        logging.info(f"Berhasil menyinkronkan {count} pengaturan pengguna individual ke cache RAM manajer.")

    except Exception as e:
        logging.error(f"Gagal total menyinkronkan pengaturan pengguna ke manajer: {e}\n{traceback.format_exc()}")
        logging.warning("Pengaturan kualitas pengguna mungkin tidak akan persisten saat restart.")


# --- Fungsi Login Qobuz ---
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
            db_settings = await database.get_variable()
            if not db_settings:
                db_settings = {}
            db_default_q = db_settings.get('QOBUZ_QUALITY')
            client.quality = int(db_default_q) if db_default_q else 6 # Default 6 (Lossless) jika tidak ada
            logging.debug(f"Berhasil memuat Kualitas Default Qobuz '{client.quality}' untuk Akun #{account_id}.")
        except Exception as e:
            logging.error(f"Gagal memuat Kualitas Default Qobuz dari DB untuk Akun #{account_id}: {e}. Menggunakan default 6.")
            client.quality = 6

        # 3. Muat Semua Pengaturan Kualitas Pengguna dari DB
        try:
            logging.debug(f"Memuat pengaturan Qobuz pengguna dari DB untuk Akun #{account_id}...")
            all_users_from_db = await database.client.users.find({}).to_list(None)
            
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
        bot_set.beatport = True 
        logging.info(f"Manajer Beatport berhasil diinisialisasi dengan {len(beatport_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Beatport yang berhasil login!")

    # 4. Login Tidal
    logging.info("Memulai inisialisasi Manajer Tidal...")
    await tidal_manager.initialize_clients()
    if tidal_manager.clients:
        logging.info(f"Manajer Tidal berhasil diinisialisasi dengan {len(tidal_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Tidal yang berhasil login! (Gunakan /settings untuk login)")

    # 5. Login KKBox
    logging.info("Memulai inisialisasi Manajer KKBox...")
    await kkbox_manager.initialize_clients()
    if kkbox_manager.clients:
        logging.info(f"Manajer KKBox berhasil diinisialisasi dengan {len(kkbox_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun KKBox yang berhasil login!")
        
    # --- TAMBAHAN: Login Beatsource ---
    logging.info("Memulai inisialisasi Manajer Beatsource...")
    await beatsource_manager.initialize_clients()
    if beatsource_manager.clients:
        # Anda mungkin ingin menambahkan: bot_set.beatsource = True 
        logging.info(f"Manajer Beatsource berhasil diinisialisasi dengan {len(beatsource_manager.clients)} klien.")
    else:
        logging.warning("PERINGATAN: Tidak ada akun Beatsource yang berhasil login!")
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN: Login Soundcloud ---
    logging.info("Memulai inisialisasi Manajer Soundcloud...")
    await soundcloud_manager.initialize_clients()
    if soundcloud_manager.get_client():
        # Anda mungkin ingin menambahkan: bot_set.soundcloud = True 
        logging.info(f"Manajer Soundcloud berhasil diinisialisasi.")
    else:
        logging.warning("PERINGATAN: Manajer Soundcloud gagal diinisialisasi (Token mungkin hilang)!")
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Login Napster ---
    if napster_manager:
        logging.info("Memulai inisialisasi Manajer Napster...")
        await napster_manager.initialize_clients()
        if napster_manager.clients:
            logging.info(f"Manajer Napster berhasil diinisialisasi dengan {len(napster_manager.clients)} klien.")
        else:
            logging.warning("PERINGATAN: Tidak ada akun Napster yang berhasil login!")
    # --- BATAS TAMBAHAN ---
    
    # --- TAMBAHAN BARU: Login Idagio ---
    if idagio_manager:
        logging.info("Memulai inisialisasi Manajer Idagio...")
        await idagio_manager.initialize_clients()
        if idagio_manager.clients:
            logging.info(f"Manajer Idagio berhasil diinisialisasi dengan {len(idagio_manager.clients)} klien.")
        else:
            logging.warning("PERINGATAN: Tidak ada akun Idagio yang berhasil login!")
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Login Nugs.net ---
    if nugs_manager:
        logging.info("Memulai inisialisasi Manajer Nugs.net...")
        await nugs_manager.initialize_clients()
        if nugs_manager.clients:
            logging.info(f"Manajer Nugs.net berhasil diinisialisasi dengan {len(nugs_manager.clients)} klien.")
        else:
            logging.warning("PERINGATAN: Tidak ada akun Nugs.net yang berhasil login!")
    # --- BATAS TAMBAHAN ---

    logging.info("Menginisialisasi data pengguna...")
    await bot_set.initialize_users()
    
    # --- PERBAIKAN: Panggil fungsi baru untuk memuat pengaturan ke RAM ---
    # Ini harus dipanggil SETELAH initialize_users() yang mengisi bot_set.user_data
    await load_all_user_settings_into_managers()
    # --- BATAS PERBAIKAN ---

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
