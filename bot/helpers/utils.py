# [FILE: bot/helpers/utils.py]

import os
import math
import aiohttp
import asyncio
import shutil
import zipfile
import typing

from pathlib import Path
from urllib.parse import quote
from aiohttp import ClientTimeout
from pyrogram.errors import MessageNotModified
from concurrent.futures import ThreadPoolExecutor
from pyrogram.errors import FloodWait

from config import Config
import bot.helpers.translations as lang

from ..logger import LOGGER
from ..settings import bot_set
from .buttons.links import links_button
from .message import send_message, edit_message

# Limit Telegram (1.9GB) untuk safety margin
MAX_SIZE = 1.9 * 1024 * 1024 * 1024 

async def download_file(url, path, retries=3, timeout=30):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024 * 4)
                                if not chunk: break
                                f.write(chunk)
                        if os.path.exists(path) and os.path.getsize(path) > 0:
                            return None
                        else:
                            if attempt == retries: return f"Download finished but file is missing: {path}"
                            await asyncio.sleep(2 ** attempt)
                            continue 
                    else:
                        if attempt == retries: return f"HTTP Status: {response.status}"
                        await asyncio.sleep(2 ** attempt)
        except Exception as e:
            if attempt == retries: return str(e)
            await asyncio.sleep(2 ** attempt)

async def format_string(text:str, data:dict, user=None):
    def safe_get(key):
        val = data.get(key)
        if val is None: return ''
        return str(val)

    title = safe_get('title')
    album = safe_get('album')
    artist = safe_get('artist')
    albumartist = safe_get('albumartist')
    tracknumber = safe_get('tracknumber')
    date = safe_get('date') 
    release_date = safe_get('release_date') 
    release_date_fallback = release_date if release_date else date
    upc = safe_get('upc')
    isrc = safe_get('isrc')
    totaltracks = safe_get('totaltracks')
    volume = safe_get('volume')
    totalvolume = safe_get('totalvolumes') or safe_get('totalvolume')
    extension = safe_get('extension')
    duration = safe_get('duration')
    copyright = safe_get('copyright')
    genre = safe_get('genre')
    provider = (data.get('provider') or '').title()
    quality = safe_get('quality')
    explicit = safe_get('explicit') 
    
    text = text.replace(R'{title}', title).replace(R'{album}', album).replace(R'{artist}', artist)
    text = text.replace(R'{albumartist}', albumartist).replace(R'{tracknumber}', tracknumber)
    text = text.replace(R'{date}', date).replace(R'{release_date}', release_date_fallback)
    text = text.replace(R'{upc}', upc).replace(R'{isrc}', isrc).replace(R'{totaltracks}', totaltracks)
    text = text.replace(R'{volume}', volume).replace(R'{totalvolume}', totalvolume)
    text = text.replace(R'{extension}', extension).replace(R'{duration}', duration)
    text = text.replace(R'{copyright}', copyright).replace(R'{genre}', genre)
    text = text.replace(R'{provider}', provider).replace(R'{quality}', quality)
    text = text.replace(R'{explicit}', explicit)

    if user:
        text = text.replace(R'{user}', user.get('name') or '').replace(R'{username}', user.get('user_name') or '')
    return text

async def run_concurrent_tasks(tasks: list, update_details: dict, limit: int = 100):
    sem = asyncio.Semaphore(limit)
    total_tasks = len(tasks)
    completed_tasks = 0
    results = []

    async def run_with_sem(task):
        nonlocal completed_tasks
        result = None 
        try:
            async with sem:
                result = await task
        except Exception: result = None
        completed_tasks += 1
        
        if update_details:
            try:
                if completed_tasks % 5 == 0 or completed_tasks == total_tasks: 
                    progress_bar = "{0}{1}".format(
                        ''.join(["▰" for _ in range(math.floor((completed_tasks/total_tasks) * 10))]),
                        ''.join(["▱" for _ in range(10 - math.floor((completed_tasks/total_tasks) * 10))])
                    )
                    text_to_send = update_details['text'].format(
                        progress_bar, completed_tasks, total_tasks,
                        update_details['title'], update_details['type'].title()
                    )
                    await edit_message(update_details['msg'], text_to_send, None, False)
            except: pass
        return result

    wrapped_tasks = [run_with_sem(task) for task in tasks]
    results = await asyncio.gather(*wrapped_tasks)
    return results

async def create_link(path, basepath):
    if isinstance(path, list): path = Path(path[0]).parent
    path = str(Path(path).relative_to(basepath))
    rclone_link, index_link = None, None

    if bot_set.link_options == 'RCLONE' or bot_set.link_options=='Both':
        cmd = f'rclone link --config ./rclone.conf "{Config.RCLONE_DEST}/{path}"'
        task = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await task.communicate()
        if task.returncode == 0: rclone_link = stdout.decode().strip()
            
    if bot_set.link_options == 'Index' or bot_set.link_options=='Both':
        if Config.INDEX_LINK: index_link =  Config.INDEX_LINK + '/' + quote(path)

    return rclone_link, index_link

# =========================================================================
#  SMART ZIP SYSTEM (TELEGRAM = SPLIT, CLOUD = SINGLE)
# =========================================================================

async def zip_handler(folderpath):
    """
    Menentukan metode ZIP berdasarkan Mode Upload Bot.
    """
    loop = asyncio.get_running_loop()
    
    # 1. JIKA TELEGRAM: Wajib Split (Safety First)
    if bot_set.upload_mode == 'Telegram':
        LOGGER.info(f"Mode Telegram terdeteksi: Menggunakan Split Zip untuk {folderpath}")
        with ThreadPoolExecutor() as pool:
            zips = await loop.run_in_executor(pool, split_zip_folder, folderpath)
        return zips
        
    # 2. JIKA CLOUD (Gofile/Buzz/dll): Wajib System Zip (Single File >2GB)
    else:
        LOGGER.info(f"Mode Cloud terdeteksi: Menggunakan System Zip (Single File) untuk {folderpath}")
        zip_file = await create_zip_system(folderpath)
        return zip_file

async def create_zip_system(folderpath):
    """
    Menggunakan aplikasi 'zip' Linux via subprocess.
    Hanya dipakai untuk Cloud Upload agar file 3GB++ tidak terpotong.
    """
    zip_path = f"{folderpath}.zip"
    
    # Command: zip -r -0 "output.zip" "." (Tanpa kompresi agar cepat)
    cmd = ["zip", "-r", "-0", zip_path, "."]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=folderpath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            final_size = os.path.getsize(zip_path)
            LOGGER.info(f"System Zip Sukses: {zip_path} ({final_size} bytes)")
            return zip_path
        else:
            LOGGER.error(f"System Zip Gagal: {stderr.decode()}")
            # Fallback ke split/python zip jika gagal
            with ThreadPoolExecutor() as pool:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(pool, zip_folder, folderpath)
                
    except FileNotFoundError:
        LOGGER.error("Command 'zip' tidak ditemukan! Pastikan sudah install 'zip' di Dockerfile.")
        with ThreadPoolExecutor() as pool:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, zip_folder, folderpath)
    except Exception as e:
        LOGGER.error(f"Error System Zip: {e}")
        return None

# Fungsi Split (Khusus Telegram - Menghasilkan .zip, .z01, .z02)
def split_zip_folder(folderpath) -> list:
    zip_paths = []
    part_num = 1
    current_size = 0
    current_files = []

    def add_to_zip(zip_name, files_to_add):
        if part_num == 1: zip_path = f"{zip_name}.zip"
        else: zip_path = f"{zip_name}.z{part_num:02d}"

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            for file_path, arcname in files_to_add:
                zipf.write(file_path, arcname)
        return zip_path

    for root, dirs, files in os.walk(folderpath):
        for file in files:
            file_path = os.path.join(root, file)
            file_size = os.path.getsize(file_path)
            arcname = os.path.relpath(file_path, folderpath)

            if current_size + file_size > MAX_SIZE:
                zip_paths.append(add_to_zip(folderpath, current_files))
                part_num += 1
                current_files = []
                current_size = 0

            current_files.append((file_path, arcname))
            current_size += file_size

    if current_files:
        zip_paths.append(add_to_zip(folderpath, current_files))
    return zip_paths

# Fungsi Legacy (Fallback)
def zip_folder(folderpath) -> str:
    zip_path = f"{folderpath}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, folderpath))
    return zip_path

# =========================================================================

async def move_sorted_playlist(metadata, user) -> str:
    source_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}/{metadata['title']}"
    os.makedirs(destination_folder, exist_ok=True)
    folders = [os.path.join(source_folder, name) for name in os.listdir(source_folder) if os.path.isdir(os.path.join(source_folder, name))]
    for folder in folders: shutil.move(folder, destination_folder)
    return destination_folder

async def post_art_poster(user:dict, meta:dict):
    photo = meta['cover']
    if meta['type'] == 'album': caption = await format_string(lang.s.ALBUM_TEMPLATE, meta, user)
    elif meta['type'] == 'artist': caption = await format_string(lang.s.ARTIST_TEMPLATE, meta, user)
    else: caption = await format_string(lang.s.PLAYLIST_TEMPLATE, meta, user)
    
    _, __, ___, art_poster = fetch_zip_settings(user)
    if art_poster:
        msg = await send_message(user, photo, 'pic', caption)
        return msg

async def create_simple_text(meta, user):
    name = meta.get('title', 'N/A')
    type_ = meta.get('type', 'N/A').title()
    provider = meta.get('provider', 'N/A')
    quality = meta.get('quality', 'N/A')
    return f"NAME : {name}\nTYPE : {type_}\nPROVIDER : {provider}\nQUALITY : {quality}"

async def edit_art_poster(metadata, user, r_link, i_link, caption):
    markup = links_button(r_link, i_link)
    await edit_message(metadata['poster_msg'], caption, markup)

async def post_simple_message(user, meta, r_link=None, i_link=None):
    caption = await create_simple_text(meta, user)
    markup = links_button(r_link, i_link)
    await send_message(user, caption, markup=markup)

async def progress_message(done, total, details):
    progress_bar = "{0}{1}".format(''.join(["▰" for i in range(math.floor((done/total) * 10))]), ''.join(["▱" for i in range(10 - math.floor((done/total) * 10))]))
    try:
        await edit_message(details['msg'], details['text'].format(progress_bar, done, total, details['title'], details['type'].title()), None, False)
    except FloodWait: pass

async def cleanup(user=None, metadata=None, user_dict: dict=None):
    if metadata:
        try:
            folder_path = metadata.get('folderpath')
            if isinstance(folder_path, str) and os.path.isdir(folder_path): shutil.rmtree(folder_path)
            elif isinstance(folder_path, list):
                for i in folder_path: 
                    if os.path.exists(i): os.remove(i)
            if metadata.get('zip_path'):
                zip_files = metadata['zip_path']
                if isinstance(zip_files, str): zip_files = [zip_files]
                for zp in zip_files: 
                    if os.path.exists(zp): os.remove(zp)
        except: pass
    if user:
        try: shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
        except: pass
        try: shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/")
        except: pass

def fetch_zip_settings(users: typing.Dict) -> typing.Tuple[bool, bool, bool, bool]:
    user_dict = bot_set.user_data.get(users.get("user_id", 0), {})
    return (user_dict.get("playlist_zip", bot_set.playlist_zip),
            user_dict.get("album_zip", bot_set.album_zip),
            user_dict.get("artist_zip", bot_set.artist_zip),
            user_dict.get("art_poster", bot_set.art_poster))
