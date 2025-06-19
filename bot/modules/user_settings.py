import bot.helpers.translations as lang
import logging
from traceback import format_exc

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config
from bot import cmd

from ..helpers.buttons.settings import usetting_button, tidal_quality_button, qb_button
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import tidalapi
from ..helpers.qobuz.qopy import qobuz_api
from ..settings import bot_set
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details

USETTING_TEXT = """
Choose Menu option bellow:
"""

@Client.on_message(filters.command(cmd.USETTING))
async def start_user_setting(client: Client, m: Message, edit=False):
    if not await check_user(msg=m):
        return
    
    user = await fetch_user_details(m)
    if not edit:
        await send_message(user, USETTING_TEXT.format(m.from_user.mention), markup=usetting_button())
        return
    await edit_message(m, USETTING_TEXT.format(m.from_user.mention), markup=usetting_button())


@Client.on_callback_query(filters.regex("^uset_(tidal|back|qobuz)"))
async def uset_cb(client, query, datatype=""):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")
    user_id = query.from_user.id
    #logging.info(data)
    if data[1] == "back":
        return await start_user_setting(client, query.message, True)
    if data[1] == "tidal" or datatype == "tidal": #(datatype == "tidal" and data[0] == "utdqs"):
        text = f"Choose Tidal Audio Quality bellow:"
        qualities = {
              'LOW': 'LOW',
              'HIGH': 'HIGH',
              'LOSSLESS': 'LOSSLESS'
        }
        user_dict = tidalapi.user_data.get(user_id, {})
        qual = user_dict.get("tidal_qual", tidalapi.quality)
        if tidalapi.mobile_hires:
            qualities['HI_RES'] = 'MAX'
        qualities[qual] += '✅'
        return await edit_message(query.message, text, tidal_quality_button(qualities, user_id))
    if data[1] == "qobuz" or datatype == "qobuz":
        text = f"Choose Qobuz Audio Quality bellow:"
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
        user_dict = qobuz_api.user_data.get(user_id, {})
        current = user_dict.get("qobuz_qual", bot_set.qobuz.quality)
        quality[current] = quality[current] + '✅'
        return await edit_message(
            query.message,
            text,
            markup=qb_button(quality, user_id)
        )

@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    to_set = query.data.split('_')[1]
    user_id = query.from_user.id
    #logging.info((to_set, query.data))
    try:
        if to_set == 'spatial':
            #options = ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']
            # assuming atleast tv session is added
            options = ['OFF', 'ATMOS AC3 JOC']
            if tidalapi.mobile_atmos:
                options.append('ATMOS AC4')
            if tidalapi.mobile_atmos or tidalapi.mobile_hires:
                options.append('Sony 360RA')
    
            user_dict = tidalapi.user_data.get(user_id, {})
            spatial = user_dict.get("tidal_spatial", tidalapi.spatial)
            #logging.info((spatial, options))
            try:
                current = options.index(spatial)
            except:
                current = 0
                
            nexti = (current + 1) % 4
            await tidalapi.setup_quality(user_id=query.from_user.id, spatial=options[nexti])
            await database.save_user_settings(query.from_user.id, tidalapi.user_data[query.from_user.id])
            #logging.info("abc")
            return await uset_cb(client, query, "tidal")
            #tidalapi.spatial = options[nexti]
            #logging.info((options, nexti)) # Debugging
            #await database.set_variable('TIDAL_SPATIAL', options[nexti])
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            #logging.info(to_set)
            #tidalapi.quality = to_set
            await tidalapi.setup_quality(user_id=query.from_user.id, qual=to_set)
            await database.save_user_settings(query.from_user.id, tidalapi.user_data[query.from_user.id])
            return await uset_cb(client, query, "tidal")
    except Exception:
        logging.error(format_exc())

@Client.on_callback_query(filters.regex("^uqbs"))
async def uset_qobuz(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    qobuz = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ',27:'24B>96KHZ'}
    to_set = query.data.split('_')[1]
    qobuz_qual = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]
    await bot_set.qobuz.setup_quality(query.from_user.id, qobuz_qual)
    await database.save_user_settings(query.from_user.id, bot_set.qobuz.user_data[query.from_user.id])
    #bot_set.qobuz.quality = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]
    #await database.set_variable('QOBUZ_QUALITY', bot_set.qobuz.quality)
    await uset_cb(client, query, "qobuz")

@Client.on_message(filters.command("debug") & filters.user(list(Config.ADMINS)))
async def debug(c, m): # debugger
    dt_qb = f"QOBUZ:\n{bot_set.qobuz.user_data}\n{bot_set.qobuz.quality}"
    dt_td = f"\n\nTIDAL:\n{bot_set.tidal.user_data}\n{bot_set.tidal.quality}\n{bot_set.tidal.spatial}"
    zips = f"{bot_set.album_zip}"
    await m.reply(dt_qb+dt_td+zips, True)