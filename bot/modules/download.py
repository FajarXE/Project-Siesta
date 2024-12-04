from pyrogram.types import Message
from pyrogram import Client, filters
from mutagen import ContentLengthError  # Import the specific error

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang
from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.message import send_message, antiSpam, check_user, fetch_user_details

# Constants for music service URLs
TIDAL_URLS = ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"]
DEEZER_URLS = ["https://deezer.page.link", "https://deezer.com", "deezer.com", "https://www.deezer.com"]
QOBUZ_URLS = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
SPOTIFY_URLS = ["https://open.spotify.com"]

@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg: Message):
    if await check_user(msg=msg):
        try:
            if msg.reply_to_message:
                link = msg.reply_to_message.text
                reply = True
            else:
                link = msg.text.split(" ", maxsplit=1)[1]
                reply = False

            if not link:
                return await send_message(msg, lang.s.ERR_LINK_RECOGNITION)

        except IndexError:
            return await send_message(msg, lang.s.ERR_NO_LINK)

        spam = await antiSpam(msg.from_user.id, msg.chat.id)
        if not spam:
            user = await fetch_user_details(msg, reply)
            user['link'] = link
            user['bot_msg'] = await send_message(msg, 'Downloading.......')
            try:
                await start_link(link, user)
                await send_message(user, lang.s.TASK_COMPLETED)
            except ContentLengthError as e:
                LOGGER.error(f"ContentLengthError: {e}")
                await send_message(msg, "There was an error processing your request due to too many requests to Qobuz. Please try again later.")
            except Exception as e:
                LOGGER.error(f"Error processing link: {e}")
                await send_message(msg, lang.s.ERR_PROCESSING_LINK)
            finally:
                await c.delete_messages(msg.chat.id, user['bot_msg'].id)
                await cleanup(user)  # Deletes uploaded files
                await antiSpam(msg.from_user.id, msg.chat.id, True)

async def start_link(link: str, user: dict):
    if link.startswith(tuple(TIDAL_URLS)):
        return "tidal"
    elif link.startswith(tuple(DEEZER_URLS)):
        return "deezer"
    elif link.startswith(tuple(QOBUZ_URLS)):
        user['provider'] = 'Qobuz'
        await start_qobuz(link, user)
    elif link.startswith(tuple(SPOTIFY_URLS)):
        return 'spotify'
    else:
        return None
