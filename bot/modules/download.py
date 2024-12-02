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
    if not await check_user(msg=msg):
        return

    link, reply = extract_link(msg)
    if not link:
        return await send_message(msg, lang.s.ERR_NO_LINK)

    if not await antiSpam(msg.from_user.id, msg.chat.id):
        user = await fetch_user_details(msg, reply)
        user['link'] = link
        user['bot_msg'] = await send_message(msg, 'Downloading.......')
        
        try:
            await start_link(link, user)
            await send_message(user, lang.s.TASK_COMPLETED)
        except Exception as e:
            LOGGER.error(e)
        finally:
            if user.get('bot_msg') and isinstance(user['bot_msg'], Message):
                await c.delete_messages(msg.chat.id, user['bot_msg'].id)
            await cleanup(user)  # deletes uploaded files
            await antiSpam(msg.from_user.id, msg.chat.id, True)


def extract_link(msg: Message):
    try:
        if msg.reply_to_message:
            return msg.reply_to_message.text, True
        else:
            return msg.text.split(" ", maxsplit=1)[1], False
    except:
        return None, False


async def start_link(link: str, user: dict):
    providers = {
        "tidal": ["https://tidal.com", "https://listen.tidal.com", "tidal.com", "listen.tidal.com"],
        "deezer": ["https://deezer.page.link", "https://deezer.com", "deezer.com", "https://www.deezer.com"],
        "qobuz": ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"],
        "spotify": ["https://open.spotify.com"]
    }

    for provider, urls in providers.items():
        if link.startswith(tuple(urls)):
            if provider == 'qobuz':
                user['provider'] = 'Qobuz'
                await start_qobuz(link, user)
            else:
                return provider

    return None
