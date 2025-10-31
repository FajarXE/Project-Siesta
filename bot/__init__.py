# --- PERBAIKAN DI SINI ---
# Mendefinisikan dictionary global agar bisa diimpor oleh file lain
BOT_QOBUZ_CLIENTS = {}
# Wadah untuk menyimpan tugas unduhan yang aktif, diindeks berdasarkan user_id
ACTIVE_DOWNLOAD_TASKS = {}
# --- BATAS PERBAIKAN ---

from config import Config
import subprocess, os

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

PORT = int(os.getenv("PORT", "0"))

subprocess.Popen([f"gunicorn server:app --bind 0.0.0.0:{PORT} --worker-class gevent"], shell=True)

class CMD(object):
    START = ["start"]
    HELP = ["help"]
    SETTINGS = ["settings"]
    DOWNLOAD = ["dl"]
    BAN = ["ban"]
    AUTH = ["auth"]
    LOG = ["log"]
    USETTING = ["usetting", "uset"]
    CANCEL = ["cancel"]

cmd = CMD()
