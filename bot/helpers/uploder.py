import asyncio
import os
import shutil

from ..settings import bot_set
from .message import send_message, edit_message
from .utils import *


async def track_upload(metadata, user, disable_link=False):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        await telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['filepath'])
        if not disable_link:
            await post_simple_message(user, metadata, rclone_link, index_link)
    await remove_file_async(metadata['filepath'])


async def album_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if bot_set.album_zip:
            tasks = [
                send_message(user, item, 'doc', caption=await create_simple_text(metadata, user))
                for item in metadata['folderpath']
            ]
            await asyncio.gather(*tasks)
        else:
            await batch_telegram_upload(metadata, user)
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link,
                                      await format_string(lang.s.ALBUM_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)
    await cleanup(None, metadata)


async def artist_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if bot_set.artist_zip:
            tasks = [
                send_message(user, item, 'doc', caption=await create_simple_text(metadata, user))
                for item in metadata['folderpath']
            ]
            await asyncio.gather(*tasks)
        else:
            pass  # artist telegram uploads are handled by album function
    else:
        rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
        if metadata['poster_msg']:
            try:
                await edit_art_poster(metadata, user, rclone_link, index_link,
                                      await format_string(lang.s.ARTIST_TEMPLATE, metadata, user))
            except MessageNotModified:
                pass
        else:
            await post_simple_message(user, metadata, rclone_link, index_link)
    await cleanup(None, metadata)


async def playlist_upload(metadata, user):
    if bot_set.upload_mode == 'Local':
        await local_upload(metadata, user)
    elif bot_set.upload_mode == 'Telegram':
        if bot_set.playlist_zip:
            tasks = [
                send_message(user, item, 'doc', caption=await create_simple_text(metadata, user))
                for item in metadata['folderpath']
            ]
            await asyncio.gather(*tasks)
        else:
            await batch_telegram_upload(metadata, user)
    else:
        if bot_set.playlist_sort and not bot_set.playlist_zip:
            if bot_set.disable_sort_link:
                await rclone_upload(user, f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            else:
                tasks = [
                    post_simple_message(user, track, *await rclone_upload(user, track['filepath']))
                    for track in metadata['tracks']
                ]
                await asyncio.gather(*tasks)
        else:
            rclone_link, index_link = await rclone_upload(user, metadata['folderpath'])
            if metadata['poster_msg']:
                try:
                    await edit_art_poster(metadata, user, rclone_link, index_link,
                                          await format_string(lang.s.PLAYLIST_TEMPLATE, metadata, user))
                except MessageNotModified:
                    pass
            else:
                await post_simple_message(user, metadata, rclone_link, index_link)


async def rclone_upload(user, realpath):
    path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
    cmd = f'rclone copy --config ./rclone.conf "{path}" "{Config.RCLONE_DEST}"'
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
    return await create_link(realpath, Config.DOWNLOAD_BASE_DIR + f"/{user['r_id']}/")


async def local_upload(metadata, user):
    to_move = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination = os.path.join(Config.LOCAL_STORAGE, os.path.basename(to_move))
    if os.path.exists(destination):
        for item in os.listdir(to_move):
            src_item = os.path.join(to_move, item)
            dest_item = os.path.join(destination, item)
            if os.path.isdir(src_item):
                if not os.path.exists(dest_item):
                    shutil.copytree(src_item, dest_item)
            else:
                shutil.copy2(src_item, dest_item)
    else:
        shutil.copytree(to_move, destination)
    shutil.rmtree(to_move)


async def telegram_upload(track, user):
    thumb = track['filepath'].replace(track['extension'], 'jpg')
    await download_file(track['thumbnail'], thumb)
    await send_message(user, track['filepath'], 'audio', thumb=thumb, meta=track)


async def batch_telegram_upload(metadata, user):
    tasks = [
        telegram_upload(track, user)
        for album in metadata.get('albums', [])
        for track in album['tracks']
    ] + [
        telegram_upload(track, user)
        for track in metadata.get('tracks', [])
    ]
    await asyncio.gather(*tasks)


async def remove_file_async(filepath):
    try:
        os.remove(filepath)
    except FileNotFoundError:
        pass


async def cleanup(_, metadata):
    if metadata.get('folderpath'):
        tasks = [remove_file_async(file) for file in metadata['folderpath']]
        await asyncio.gather(*tasks)
