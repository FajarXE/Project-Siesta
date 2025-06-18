import bot.helpers.translations as lang
import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config
from bot import cmd

from ..helpers.buttons.settings import usetting_button, tidal_quality_button
from ..helpers.tidal.tidal_api import tidalapi
from ..settings import bot_set
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details

USETTING_TEXT = """
Hi {}
Choose Menu option bellow:
"""

@Client.on_message(filters.command(cmd.USETTING))
async def start_user_setting(client: Client, m: Message):
    if not await check_user(msg=m):
        return
    
    user = await fetch_user_details(m)
    await send_message(user, USETTING_TEXT.format(m.from_user.mention), markup=usetting_button())


@Client.on_callback_query(filters.regex("^uset_(tidal|back)"))
async def uset_cb_tidal(client, query):
    if not await check_user(msg=query.message):
        return
    data = query.data.split("_")
    logging.info(data)
    user_id = query.from_user.id
    #if options == "tidal":
    text = f"Choose Tidal Audio Quality bellow:"
    qualities = {
          'LOW': 'LOW',
          'HIGH': 'HIGH',
          'LOSSLESS': 'LOSSLESS'
    }
    user_dict = tidalapi.user_data.get(user_id, {})
    qual = user_dict.get("formats", tidalapi.quality)
    #spatial = user_dict.get("spatial", tidalapi.spatial)
    if tidalapi.mobile_hires:
        qualities['HI_RES'] = 'MAX'
    qualities[qual] += '✅'
    #logging.info(qualities)
    #logging.info(qualities[qual])
    await edit_message(query.message, text, tidal_quality_button(qualities, user_id))
    

@Client.on_callback_query(filters.regex("^utdqs"))
async def uset_tidal(client, query):
    m = query.message
    if not await check_user(msg=m):
        return
    to_set = query.data.split('_')[1]
    user_id = query.from_user.id
    #logging.info((to_set, query.data))
    if to_set == 'spatial':
        #options = ['OFF', 'ATMOS AC3 JOC', 'ATMOS AC4', 'Sony 360RA']
        # assuming atleast tv session is added
        options = ['OFF', 'ATMOS AC3 JOC']
        if tidalapi.mobile_atmos:
            options.append('ATMOS AC4')
        if tidalapi.mobile_atmos or tidalapi.mobile_hires:
            options.append('Sony 360RA')

        user_dict = tidalapi.user_data.get(user_id, {})
        spatial = user_dict.get("spatial", tidalapi.spatial)
        #logging.info((spatial, options))
        try:
            current = options.index(spatial)
        except:
            current = 0
            
        nexti = (current + 1) % 4
        await tidalapi.setup_quality(user_id=query.from_user.id, spatial=options[nexti])
        #tidalapi.spatial = options[nexti]
        #logging.info((options, nexti)) # Debugging
        #await database.set_variable('TIDAL_SPATIAL', options[nexti])
    else:
        qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
        to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
        #logging.info(to_set)
        #tidalapi.quality = to_set
        await tidalapi.setup_quality(user_id=query.from_user.id, qual=to_set)
    await uset_cb_tidal(client, query)
    

@Client.on_message(filters.command("debug") & filters.user(list(Config.ADMINS)))
async def debug(c, m): # debugger
    t = f"{tidalapi.user_data}\n\n{tidalapi.quality}\n\n{tidalapi.spatial}"
    await m.reply(t, True)