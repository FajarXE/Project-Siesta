from pyrogram.types import Message
from pyrogram import Client, filters

from bot import CMD
from bot.logger import LOGGER

import bot.helpers.translations as lang

from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.message import send_message, antiSpam, check_user, fetch_user_details

@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg: Message):
    if await check_user(msg=msg):
        link = await extract_link(msg)
        if not link:
            return await send_message(msg, lang.s.ERR_NO_LINK)

        spam = await antiSpam(msg.from_user.id, msg.chat.id)
        if not spam:
            user = await fetch_user_details(msg)
            user['link'] = link
            user['bot_msg'] = await send_message(msg, 'Downloading...')
            try:
                await start_link(link, user)
                await send_message(msg, lang.s.TASK_COMPLETED)
            except Exception as e:
                LOGGER.error(f"Error during download: {e}")
                await send_message(msg, lang.s.ERR_DOWNLOAD_FAILED)
            finally:
                await c.delete_messages(msg.chat.id, user['bot_msg'].id)
                await cleanup(user)  # deletes uploaded files
                await antiSpam(msg.from_user.id, msg.chat.id, True)

async def extract_link(msg: Message):
    """Extracts the download link from the message."""
    if msg.reply_to_message:
        return msg.reply_to_message.text
    else:
        try:
            return msg.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return None

async def start_link(link: str, user: dict):
    """Determines the provider and initiates the download."""
    tidal = ["https://tidal.com", "https://listen.tidal.com"]
    deezer = ["https://deezer.page.link", "https://deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]

    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        # Handle Tidal download here (implement the function accordingly)
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        # Handle Deezer download here (implement the function accordingly)
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'
        await start_qobuz(link, user)  # Ensure this function is implemented correctly
    elif link.startswith(tuple(spotify)):
        user['provider'] = 'Spotify'
        # Handle Spotify download here (implement the function accordingly)
    else:
        LOGGER.warning(f"Unsupported link: {link}")
        await send_message(user['bot_msg'], lang.s.ERR_UNSUPPORTED_LINK)
