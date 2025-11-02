from config import Config
import subprocess, os

bot = Config.BOT_USERNAME

plugins = dict(
    root="bot/modules"
)

# Note: previously this module started gunicorn on import. That caused a
# side-effect where importing the `bot` package (for example by
# `python -m bot`) spawned a separate process which could import the
# project again and lead to multiple Pyrogram clients using the same
# session file simultaneously (AuthKeyDuplicated). Avoid spawning
# background processes on import. Start web server explicitly from
# a dedicated entrypoint (start.sh / docker command) if needed.
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
