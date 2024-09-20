from config import Config
import subprocess, os

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

PORT = int(os.getenv("PORT"))

subprocess.Popen([f"gunicorn server:app --bind 0.0.0.0:{PORT} --worker-class gevent"], shell=True)

class CMD(object):
    START = ["start", f"start@{bot}"]
    HELP = ["help", f"help@{bot}"]
    SETTINGS = ["settings", f"settings@{bot}"]
    DOWNLOAD = ["dl", f"dl@{bot}"]
    BAN = ["ban", f"ban@{bot}"]
    AUTH = ["auth", f"auth@{bot}"]

cmd = CMD()
