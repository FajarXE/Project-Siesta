# [GANTI FILE: bot/__main__.py]

import os
import signal
import asyncio
import sys
import logging
import traceback
from pyrogram import idle # PENTING: Gunakan idle resmi

from bot import Config
from .tgclient import aio
from .settings import bot_set

# --- Blok Impor Qobuz ---
try:
    from .helpers.qobuz.qopy import QoClient
except ImportError:
    logging.critical("Gagal mengimpor QoClient!")
    sys.exit(1)
from bot import BOT_QOBUZ_CLIENTS

try:
    from .helpers.database.mongo_async import database
except ImportError:
    logging.critical("Gagal mengimpor 'database'!")
    sys.exit(1)

# --- Impor Manajer Layanan (Safe Imports) ---
def safe_import(module_path, class_name):
    try:
        mod = __import__(module_path, fromlist=[class_name])
        return getattr(mod, class_name)
    except (ImportError, AttributeError):
        return None

deezer_manager = safe_import('bot.helpers.deezer.manager', 'deezer_manager')
beatport_manager = safe_import('bot.helpers.beatport.manager', 'beatport_manager')
tidal_manager = safe_import('bot.helpers.tidal.manager', 'tidal_manager')
kkbox_manager = safe_import('bot.helpers.kkbox.manager', 'kkbox_manager')
beatsource_manager = safe_import('bot.helpers.beatsource.manager', 'beatsource_manager')
soundcloud_manager = safe_import('bot.helpers.soundcloud.manager', 'soundcloud_manager')
napster_manager = safe_import('bot.helpers.napster.manager', 'napster_manager')
idagio_manager = safe_import('bot.helpers.idagio.manager', 'idagio_manager')
nugs_manager = safe_import('bot.helpers.nugs.manager', 'nugs_manager')
bugs_manager = safe_import('bot.helpers.bugs.manager', 'bugs_manager')
highresaudio_manager = safe_import('bot.helpers.highresaudio.manager', 'highresaudio_manager')
moov_manager = safe_import('bot.helpers.moov.manager', 'moov_manager')
jiosaavn_manager = safe_import('bot.helpers.jiosaavn.manager', 'jiosaavn_manager')
gaana_manager = safe_import('bot.helpers.gaana.manager', 'gaana_manager')
bandcamp_manager = safe_import('bot.helpers.bandcamp.manager', 'bandcamp_manager')
livephish_manager = safe_import('bot.helpers.livephish.manager', 'livephish_manager')
beatstars_manager = safe_import('bot.helpers.beatstars.manager', 'beatstars_manager')
khinsider_manager = safe_import('bot.helpers.khinsider.manager', 'khinsider_manager')


async def load_all_user_settings_into_managers():
    logging.info("Main: Sinkronisasi pengaturan pengguna ke cache manajer...")
    try:
        count = 0
        settings_map = {
            'deezer_qual': deezer_manager,
            'beatport_qual': beatport_manager,
            'kkbox_qual': kkbox_manager,
            'beatsource_qual': beatsource_manager,
            'soundcloud_qual': soundcloud_manager,
            'napster_qual': napster_manager,
            'idagio_qual': idagio_manager,
            'bugs_qual': bugs_manager,
            'moov_qual': moov_manager,
            'livephish_qual': livephish_manager,
            'khinsider_qual': khinsider_manager,
        }

        # Pastikan user_data sudah terisi
        if not bot_set.user_data:
            logging.warning("Main: bot_set.user_data kosong/belum dimuat.")
            return

        # --- FIX: Ambil Referensi Client Qobuz (Untuk Sinkronisasi) ---
        qobuz_interface = None
        if BOT_QOBUZ_CLIENTS:
            # Ambil client pertama saja karena mereka berbagi database JSON yang sama (di qopy.py baru)
            qobuz_interface = list(BOT_QOBUZ_CLIENTS.values())[0]
        # --------------------------------------------------------------

        for user_id, user_data in bot_set.user_data.items():
            if not user_id: continue
            
            # 1. Sinkronisasi Manager Standar
            for key, manager in settings_map.items():
                quality_val = user_data.get(key)
                if quality_val and manager:
                    try:
                        await manager.setup_quality(user_id, quality_val)
                        count += 1
                    except Exception: pass
            
            # 2. Sinkronisasi QOBUZ (Manual, karena tidak masuk settings_map)
            # Ini akan menulis ulang setting dari Mongo ke file JSON qobuz saat startup
            if qobuz_interface and user_data.get('qobuz_qual'):
                try:
                    await qobuz_interface.setup_quality(user_id, user_data['qobuz_qual'])
                    count += 1
                except Exception: pass

        logging.info(f"Main: Berhasil menyinkronkan {count} pengaturan.")
    except Exception as e:
        logging.error(f"Main: Gagal sinkronisasi pengaturan pengguna: {e}")


async def login_single_client(creds: dict):
    creds_copy = creds.copy()
    account_id = creds_copy.pop("id", "Unknown")
    client = QoClient(**creds_copy) 
    try:
        await client.login()
        BOT_QOBUZ_CLIENTS[account_id] = client
        logging.info(f"Main: Qobuz #{account_id} LOGIN SUKSES.")
    except Exception as e:
        logging.error(f"Main: Qobuz #{account_id} GAGAL: {e}")
        await client.close_session()

async def load_all_bot_qobuz_clients():
    if not Config.QOBUZ_ACCOUNTS: return
    logging.info(f"Main: Mencoba login {len(Config.QOBUZ_ACCOUNTS)} akun Qobuz...")
    tasks = [login_single_client(acc) for acc in Config.QOBUZ_ACCOUNTS]
    await asyncio.gather(*tasks)


async def start_services():
    """Fungsi inisialisasi utama."""
    logging.info("------------------------------------------------")
    logging.info("Main: Memulai Inisialisasi Layanan...")
    
    await bot_set.set_language()
    
    # 1. Start Qobuz
    await load_all_bot_qobuz_clients()

    # 2. Start Managers
    managers = [
        (deezer_manager, "Deezer"), (beatport_manager, "Beatport"), 
        (tidal_manager, "Tidal"), (kkbox_manager, "KKBox"),
        (beatsource_manager, "Beatsource"), (soundcloud_manager, "Soundcloud"),
        (napster_manager, "Napster"), (idagio_manager, "Idagio"),
        (nugs_manager, "Nugs"), (bugs_manager, "Bugs"),
        (highresaudio_manager, "HIGHRESAUDIO"), (moov_manager, "Moov"),
        (jiosaavn_manager, "JioSaavn"), (gaana_manager, "Gaana"), 
        (bandcamp_manager, "Bandcamp"), (livephish_manager, "LivePhish"), 
        (beatstars_manager, "BeatStars"), (khinsider_manager, "Khinsider")
    ]

    for mgr, name in managers:
        if mgr:
            logging.info(f"Main: Menginisialisasi {name}...")
            try: 
                # Gunakan timeout agar jika macet tidak selamanya
                await asyncio.wait_for(mgr.initialize_clients(), timeout=45.0)
                logging.info(f"Main: {name} OK.")
            except asyncio.TimeoutError:
                logging.error(f"Main: {name} TIMEOUT (Melewati...)")
            except Exception as e: 
                logging.error(f"Main: Gagal init {name}: {e}")

    # Set flags
    if deezer_manager and deezer_manager.clients: bot_set.deezer = True 
    if beatport_manager and beatport_manager.clients: bot_set.beatport = True 

    # 3. Load User Data
    logging.info("Main: Memuat Database Pengguna...")
    await bot_set.initialize_users()
    await load_all_user_settings_into_managers()

    # 4. Start Telegram Client
    logging.info("Main: Menghubungkan ke Telegram...")
    await aio.start()
    
    me = await aio.get_me()
    logging.info(f"------------------------------------------------")
    logging.info(f"BOT BERHASIL START SEBAGAI: @{me.username}")
    logging.info(f"------------------------------------------------")
    
    # 5. Keep Alive dengan IDLE
    await idle()
    
    # 6. Stop Sequence (After Idle breaks)
    logging.info("Main: Menerima sinyal stop, mematikan layanan...")
    await aio.stop()
    await shutdown_all_services()


async def shutdown_all_services():
    tasks = []
    # Close Qobuz
    for client in BOT_QOBUZ_CLIENTS.values():
        if client and hasattr(client, 'close_session'):
            tasks.append(client.close_session())
    
    # Close Managers
    managers_list = [
        deezer_manager, beatport_manager, tidal_manager, kkbox_manager,
        beatsource_manager, soundcloud_manager, napster_manager, idagio_manager,
        nugs_manager, bugs_manager, highresaudio_manager, moov_manager,
        jiosaavn_manager, gaana_manager, bandcamp_manager, livephish_manager, beatstars_manager, khinsider_manager
    ]
    for mgr in managers_list:
        if mgr and hasattr(mgr, 'shutdown'):
            tasks.append(mgr.shutdown())

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    
    # Gunakan get_event_loop agar konsisten dengan environment Pyrogram
    loop = asyncio.get_event_loop()
    
    try:
        loop.run_until_complete(start_services())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Main: Dipaksa berhenti oleh pengguna.")
    except Exception as e:
        logging.critical(f"Main: ERROR FATAL UTAMA: {e}")
        traceback.print_exc()
    finally:
        logging.info("Main: Selesai.")
