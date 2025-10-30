import os
import signal
import asyncio, sys, logging, traceback

from bot import Config

from .tgclient import aio
from .settings import bot_set

# --- MODIFIKASI DIMULAI ---
# 1. Impor QoClient (Sesuaikan path ini jika perlu!)
try:
    # Asumsi path 'bot/qobuz/qopy.py'
    from .qobuz.qopy import QoClient
except ImportError:
    logging.critical("Gagal mengimpor QoClient! Pastikan path 'from .qobuz.qopy import QoClient' benar.")
    sys.exit(1)

# 2. Buat dictionary global untuk menyimpan klien yang sudah login
# Handler/modul lain akan mengimpor ini
BOT_QOBUZ_CLIENTS = {}

async def login_single_client(creds: dict):
    """Helper untuk meloginkan satu klien dan menyimpannya."""
    # Buat salinan agar .pop() tidak merusak list asli
    creds_copy = creds.copy()
    account_id = creds_copy.pop("id") # Ambil ID unik (1, 2, 3...)
    
    try:
        # **creds_copy akan meneruskan 'email'/'password' atau 'user_id'/'user_token'
        client = QoClient(**creds_copy) 
        
        await client.login()
        
        # 3. Simpan klien yang SUDAH LOGIN ke dictionary global
        BOT_QOBUZ_CLIENTS[account_id] = client
        logging.info(f"Berhasil login akun Qobuz #{account_id} (Label: {client.label})")
        
    except Exception as e:
        logging.error(f"Gagal login akun Qobuz #{account_id}: {e}")

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
        logging.info(f"Berhasil login {len(BOT_QOBUZ_CLIENTS)} akun Qobuz.")
# --- MODIFIKASI SELESAI ---


def signal_handler(s, f):
    try:
        logging.info("Signal received! Exiting....")
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)


async def main():
    await bot_set.set_language()
    
    # --- MODIFIKASI DIMULAI ---
    # 4. Panggil fungsi login Qobuz SEBELUM bot online
    await load_all_bot_qobuz_clients()
    # --- MODIFIKASI SELESAI ---

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
