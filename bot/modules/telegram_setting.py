import logging, asyncio

import bot.helpers.translations as lang

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from ..settings import bot_set
from ..helpers.translations import lang_available
from ..helpers.buttons.settings import tg_button, language_buttons
from ..helpers.database.mongo_async import database
from ..helpers.message import edit_message, check_user



@Client.on_callback_query(filters.regex(pattern=r"^tgPanel"))
async def tg_cb(c, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message, 
            lang.s.TELEGRAM_PANEL.format(
                bot_set.bot_public,
                bot_set.bot_lang,
                len(bot_set.admins),
                len(bot_set.auth_users),
                len(bot_set.auth_chats),
                bot_set.upload_mode
            ),
            markup=tg_button()
        )


@Client.on_callback_query(filters.regex(pattern=r"^botPublic"))
async def bot_public_cb(client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        bot_set.bot_public = False if bot_set.bot_public else True
        await database.set_variable('BOT_PUBLIC', bot_set.bot_public)
        await tg_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^antiSpam"))
async def anti_spam_cb(client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        anti = ['OFF', 'USER', 'CHAT+']
        current = anti.index(bot_set.anti_spam)
        nexti = (current + 1) % 3
        bot_set.anti_spam = anti[nexti]
        await database.set_variable('ANTI_SPAM', anti[nexti])
        await tg_cb(client, cb)



@Client.on_callback_query(filters.regex(pattern=r"^langPanel"))
async def language_panel_cb(client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        current = bot_set.bot_lang
        #logging.info((current, bot_set.bot_lang))
        await edit_message(
            cb.message,
            lang.s.LANGUAGE_PANEL,
            markup=language_buttons(lang_available, current)
        )



@Client.on_callback_query(filters.regex(pattern=r"^langSet"))
async def set_language_cb(client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        logging.info(to_set)
        bot_set.bot_lang = to_set
        await database.set_variable('BOT_LANGUAGE', to_set)
        await bot_set.set_language()
        await language_panel_cb(client, cb)
