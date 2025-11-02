from config import Config
import subprocess, os

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

subprocess.Popen([f"gunicorn server:app --bind 0.0.0.0:{PORT} --worker-class gevent"], shell=True)
PORT = int(os.getenv("PORT", "0"))

class CMD(object):
    START = ["start"]
    HELP = ["help"]
    SETTINGS = ["settings"]
    DOWNLOAD = ["dl"]
    BAN = ["ban"]
    AUTH = ["auth"]
    LOG = ["log"]
    USETTING = ["usetting", "uset"]

cmd = CMD()
