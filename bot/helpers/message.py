# [GANTI SELURUH FILE: bot/helpers/message.py]

import os
import asyncio
import time
import math
import traceback 

from pyrogram.types import Message
from pyrogram.errors import MessageNotModified, FloodWait, MessageIdInvalid, RPCError

# Impor global client untuk fallback
from bot.tgclient import aio
from bot.settings import bot_set
from bot.logger import LOGGER


current_user = []

user_details = {
    'user_id': None,
    'name': None, 
    'user_name': None, 
    'r_id': None, 
    'chat_id': None,
    'provider': None,
    'bot_msg': None,
    'link': None,
    'override' : None 
}


async def fetch_user_details(msg: Message, reply=False) -> dict:
    details = user_details.copy()
    details['user_id'] = msg.from_user.id
    details['name'] = msg.from_user.first_name
    if msg.from_user.username:
        details['user_name'] = msg.from_user.username
    else:
        details['user_name'] = msg.from_user.mention()
    details['r_id'] = msg.reply_to_message.id if reply else msg.id
    details['chat_id'] = msg.chat.id
    try:
        details['bot_msg'] = msg
    except:
        pass
    return details


async def check_user(uid=None, msg=None, restricted=False) -> bool:
    if restricted:
        if uid in bot_set.admins:
            return True
    else:
        if bot_set.bot_public:
            return True
        else:
            all_chats = list(bot_set.admins) + bot_set.auth_chats + bot_set.auth_users 
            if msg.from_user.id in all_chats:
                return True
            elif msg.chat.id in all_chats:
                return True
    return False


async def antiSpam(uid=None, cid=None, revoke=False) -> bool:
    if revoke:
        if bot_set.anti_spam == 'CHAT+':
            if cid in current_user:
                current_user.remove(cid)
        elif bot_set.anti_spam == 'USER':
            if uid in current_user:
                current_user.remove(uid)
    else:
        if bot_set.anti_spam == 'CHAT+':
            if cid in current_user:
                return True
            else:
                current_user.append(cid)
        elif bot_set.anti_spam == 'USER':
            if uid in current_user:
                return True
            else:
                current_user.append(uid)
        return False


async def send_message(user, item, itype='text',
    caption=None, markup=None, chat_id=None,
    meta=None
  ):
    if not isinstance(user, dict):
        user = await fetch_user_details(user)
    chat_id = chat_id if chat_id else user['chat_id']

    try:
        if itype == 'text':
            msg = await aio.send_message(
                chat_id=chat_id,
                text=item,
                reply_to_message_id=user['r_id'],
                reply_markup=markup,
                disable_web_page_preview=True
            )
            
        elif itype == 'doc':
            thumb_path = None
            if meta and meta.get('cover'): 
                if os.path.exists(meta['cover']):
                    thumb_path = meta['cover']

            last_update_time = [0] 

            async def progress_callback(current, total):
                current_time = time.time()
                if current_time - last_update_time[0] < 5:
                    return
                last_update_time[0] = current_time

                percentage = int((current / total) * 100)
                progress_bar = "{0}{1}".format(
                    ''.join(["▰" for i in range(math.floor(percentage / 10))]),
                    ''.join(["▱" for i in range(10 - math.floor(percentage / 10))])
                )
                
                try:
                    text = (
                        f"**Mengunggah file .zip...**\n"
                        f"`{os.path.basename(item)}`\n\n"
                        f"{progress_bar} {percentage}%"
                    )
                    # Gunakan create_task agar tidak memblokir upload
                    asyncio.create_task(edit_message(user['bot_msg'], text, antiflood=False))
                except Exception:
                    pass
            
            msg = await aio.send_document(
                chat_id=chat_id,
                document=item,
                caption=caption,
                reply_to_message_id=user['r_id'],
                thumb=thumb_path,
                progress=progress_callback
            )

        elif itype == 'audio':
            thumb_path = None
            cover_candidate = meta.get('cover') or meta.get('thumbnail')
            if cover_candidate and isinstance(cover_candidate, str):
                if os.path.exists(cover_candidate):
                    thumb_path = cover_candidate
            
            duration = 0
            raw_duration = meta.get('duration')
            if raw_duration:
                try:
                    duration = int(float(str(raw_duration)))
                except:
                    duration = 0

            progress_callback = None 
            
            if meta and not meta.get('batch_mode', False) and user.get('bot_msg'):
                last_update_time = [0]

                async def internal_progress_callback(current, total):
                    current_time = time.time()
                    if current_time - last_update_time[0] < 5:
                        return
                    last_update_time[0] = current_time

                    percentage = int((current / total) * 100)
                    progress_bar = "{0}{1}".format(
                        ''.join(["▰" for i in range(math.floor(percentage / 10))]),
                        ''.join(["▱" for i in range(10 - math.floor(percentage / 10))])
                    )
                    
                    try:
                        track_num = meta.get('tracknumber', '?')
                        total_tracks = meta.get('totaltracks', '?')
                        title = meta.get('title', 'Unknown Track')
                        
                        text = (
                            f"**Mengunggah...**\n"
                            f"Lagu {track_num} dari {total_tracks}\n" 
                            f"`{title}`\n\n"
                            f"{progress_bar} {percentage}%"
                        )
                        asyncio.create_task(edit_message(user['bot_msg'], text, antiflood=False))
                    except Exception:
                        pass
                
                progress_callback = internal_progress_callback 
            
            msg = await aio.send_audio(
                chat_id=chat_id,
                audio=item,
                caption=caption,
                duration=duration,
                performer=meta.get('artist'),
                title=meta.get('title'),
                thumb=thumb_path, 
                reply_to_message_id=user['r_id'],
                progress=progress_callback
            )

        elif itype == 'pic':
            msg = await aio.send_photo(
                chat_id=chat_id,
                photo=item,
                caption=caption,
                reply_to_message_id=user['r_id']
            )

    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_message(user, item, itype, caption, markup, chat_id, meta)
    except Exception as e:
        LOGGER.error(f"Send Message Error: {e}")
        return None

    return msg


# --- FUNGSI UTAMA YANG DIPERBAIKI ---
async def edit_message(msg: Message, text: str, markup=None, antiflood=True):
    """
    Mengedit pesan dengan fallback ke 'aio.edit_message_text' 
    jika 'msg.edit_text' gagal karena masalah koneksi.
    """
    if not msg:
        return None

    try:
        # METODE 1: Coba edit langsung dari objek pesan (Standard)
        # Cek msg._client agar tidak error "Client has not been started yet"
        if msg._client and msg._client.is_connected:
            return await msg.edit_text(
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True
            )
        
        # METODE 2: Fallback ke Klien Global (aio)
        # Jika metode 1 gagal atau klien terputus, gunakan ini.
        elif aio.is_connected:
            return await aio.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.id,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True
            )
        else:
            LOGGER.warning("Edit Message: Gagal, kedua klien (msg & aio) tidak terhubung.")
            return None

    except MessageNotModified:
        pass # Isi pesan sama, abaikan
    except FloodWait as e:
        if antiflood:
            await asyncio.sleep(e.value)
            return await edit_message(msg, text, markup, antiflood)
    except MessageIdInvalid:
        pass # Pesan sudah dihapus
    except RPCError as e:
        LOGGER.error(f"RPCError Edit Message: {e}")
    except Exception as e:
        # Log error generik, tapi jangan crash
        LOGGER.error(f"Error Edit Message: {e}")
        return None
