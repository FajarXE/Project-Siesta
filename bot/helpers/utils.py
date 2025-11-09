# [GANTI FILE: bot/helpers/utils.py]

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
from pyrogram.errors import FloodWait, MessageIdInvalid # <-- Import yang saya tambahkan terakhir

from config import Config
import bot.helpers.translations as lang

from ..logger import LOGGER
from ..settings import bot_set
from .buttons.links import links_button
from .message import send_message, edit_message


MAX_SIZE = 1.9 * 1024 * 1024 * 1024  # 2GB
# download folder structure : BASE_DOWNLOAD_DIR + message_r_id

async def download_file(url, path, retries=3, timeout=30):
    """
    Args:
        url (str): URL to download.
        path (str): Path including filename with extension.
        retries (int): Number of retries in case of failure.
        timeout (int): Timeout duration for the request in seconds.
    Returns:
        str or None: Error message if any, else None.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    for attempt in range(1, retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024 * 4)
                                if not chunk:
                                    break
                                f.write(chunk)
                        
                        # VERIFIKASI SETELAH DOWNLOAD
                        if os.path.exists(path) and os.path.getsize(path) > 0:
                            return None  # Sukses
                        else:
                            if attempt == retries:
                                return f"Download finished but file is missing or empty: {path}"
                            await asyncio.sleep(2 ** attempt)
                            continue # Coba lagi jika file kosong/hilang

                    # Tangani URL unduhan yang gagal (misal 403/404 dari URL sementara)
                    else:
                        if attempt == retries:
                            return f"HTTP Status: {response.status} (URL: {url})"
                        await asyncio.sleep(2 ** attempt)

        except aiohttp.ClientError as e:
            if attempt == retries:
                return f"Connection failed after {retries} attempts: {str(e)}"
            await asyncio.sleep(2 ** attempt)
        except asyncio.TimeoutError:
            if attempt == retries:
                return "Download failed due to timeout."
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            # Selalu kembalikan string untuk error
            return str(e)


# --- FUNGSI YANG DIPERBAIKI (LOGIKA AMAN) ---
async def format_string(text:str, data:dict, user=None):
    """
    Args:
        text: text to be formatted
        data: source info
        user: user details
    Returns:
        str
    """
    
    # Fungsi helper internal untuk menangani None vs False
    def safe_get(key):
        val = data.get(key)
        # Jika nilainya None (tidak ada), kembalikan string kosong
        if val is None:
            return ''
        # Jika nilainya ada (termasuk True atau False), konversi ke string
        return str(val)

    # Ambil semua data dengan aman
    title = safe_get('title')
    album = safe_get('album')
    artist = safe_get('artist')
    albumartist = safe_get('albumartist')
    tracknumber = safe_get('tracknumber')
    date = safe_get('date')
    upc = safe_get('upc')
    isrc = safe_get('isrc')
    totaltracks = safe_get('totaltracks')
    volume = safe_get('volume')
    
    # --- PERBAIKAN: Periksa 'totalvolumes' (plural) DAHULU, lalu 'totalvolume' (singular) ---
    totalvolume = safe_get('totalvolumes') or safe_get('totalvolume')
    # --- BATAS PERBAIKAN ---

    extension = safe_get('extension')
    duration = safe_get('duration')
    copyright = safe_get('copyright')
    genre = safe_get('genre')
    provider = (data.get('provider') or '').title() # .title() aman
    quality = safe_get('quality')
    explicit = safe_get('explicit') 
    
    # Lakukan penggantian dengan nilai yang aman
    text = text.replace(R'{title}', title)
    text = text.replace(R'{album}', album)
    text = text.replace(R'{artist}', artist)
    text = text.replace(R'{albumartist}', albumartist)
    text = text.replace(R'{tracknumber}', tracknumber)
    text = text.replace(R'{date}', date)
    text = text.replace(R'{upc}', upc)
    text = text.replace(R'{isrc}', isrc)
    text = text.replace(R'{totaltracks}', totaltracks)
    text = text.replace(R'{volume}', volume)
    
    # --- PERBAIKAN: Gunakan 'totalvolume' (singular) untuk placeholder template ---
    text = text.replace(R'{totalvolume}', totalvolume)
    # --- BATAS PERBAIKAN ---

    text = text.replace(R'{extension}', extension)
    text = text.replace(R'{duration}', duration)
    text = text.replace(R'{copyright}', copyright)
    text = text.replace(R'{genre}', genre)
    text = text.replace(R'{provider}', provider)
    text = text.replace(R'{quality}', quality)
    text = text.replace(R'{explicit}', explicit)

    if user:
        text = text.replace(R'{user}', user.get('name') or '')
        text = text.replace(R'{username}', user.get('user_name') or '')
    return text
# --- AKHIR PERBAIKAN ---


async def run_concurrent_tasks(tasks, progress_details=None):
    """
    Args:
        tasks: (list) async functions to be run
        progress_details: details for progress message (dict)    
    Returns:
        List[bool]: Daftar hasil (True/False) dari setiap task.
    """
    semaphore = asyncio.Semaphore(Config.MAX_WORKERS)

    i = [0]
    l = len(tasks)
    async def sem_task(task):
        async with semaphore:
            try:
                # Jalankan task (misal: start_track)
                result = await task 
            except Exception as e:
                # Diubah ke .info() agar tidak mengganggu log
                LOGGER.info(f"Satu task di run_concurrent_tasks gagal (tapi ditangani): {e}")
                result = False # Memberi sinyal kegagalan
            
            if progress_details and result: # Hanya update progress jika 'start_track' mengembalikan True (sukses)
                i[0]+=1 # currently done
                await progress_message(i[0], l, progress_details)
            
            # Kembalikan hasil (meskipun False) agar gather bisa menangkapnya
            return result 

    # 'await asyncio.gather' akan menjalankan semua 'sem_task'
    # 'sem_task' internal try/except akan mencegah satu kegagalan
    # menghentikan yang lain.
    
    return await asyncio.gather(*(sem_task(task) for task in tasks))


async def create_link(path, basepath):
    """
    Creates rclone and index link
    Args:
        path: full real path
        basepath: to remove bot folder from real path (DOWNLOADS/r_id/)
    Returns:
        rclone_link: link from rclone
        index_link: index link if enabled
    """
    # --- PERBAIKAN: Tangani jika path adalah list (dari zip split) ---
    if isinstance(path, list):
        # Jika ini adalah list, kita tidak bisa membuat link ke semua,
        # jadi kita buat link ke direktori induknya.
        path = Path(path[0]).parent
    # --- AKHIR PERBAIKAN ---

    path = str(Path(path).relative_to(basepath))

    rclone_link = None
    index_link = None

    if bot_set.link_options == 'RCLONE' or bot_set.link_options=='Both':
        cmd = f'rclone link --config ./rclone.conf "{Config.RCLONE_DEST}/{path}"'
        task = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await task.communicate()

        if task.returncode == 0:
            rclone_link = stdout.decode().strip()
        else:
            error_message = stderr.decode().strip()
            LOGGER.debug(f"Failed to get link: {error_message}")
    if bot_set.link_options == 'Index' or bot_set.link_options=='Both':
        if Config.INDEX_LINK:
            index_link =  Config.INDEX_LINK + '/' + quote(path)

    return rclone_link, index_link


async def zip_handler(folderpath):
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        if bot_set.upload_mode == 'Telegram':
            zips = await loop.run_in_executor(pool, split_zip_folder, folderpath)
        else:
            zips = await loop.run_in_executor(pool, zip_folder, folderpath)
        return zips


def split_zip_folder(folderpath) -> list:
    """
    Args:
        folderpath: path to folder to zip
    Returns:
        list of zip file paths
    """
    zip_paths = []
    part_num = 1
    current_size = 0
    current_files = []

    def add_to_zip(zip_name, files_to_add):
        if part_num == 1:
            zip_path = f"{zip_name}.zip"
        else:
            zip_path = f"{zip_name}.z{part_num:02d}"

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            for file_path, arcname in files_to_add:
                zipf.write(file_path, arcname)
                # --- PERBAIKAN: JANGAN HAPUS FILE DI SINI ---
                # os.remove(file_path)  
                # --- AKHIR PERBAIKAN ---
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


def zip_folder(folderpath) -> str:
    """
    Args:
        folderpath (str): The path of the folder to zip.
    Returns:
        str: The path to the created zip file.
    """
    zip_path = f"{folderpath}.zip"
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, folderpath))
                # --- PERBAIKAN: JANGAN HAPUS FILE DI SINI ---
                # os.remove(file_path)
                # --- AKHIR PERBAIKAN ---
    
    return zip_path


async def move_sorted_playlist(metadata, user) -> str:
    """
    Moves the sorted playlist files into a new playlist folder.
    Used since sorted tracks doest belong to a specific palylist folder
    Returns:
        str: path to the newly created playlist folder
    """

    source_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
    destination_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}/{metadata['title']}"

    os.makedirs(destination_folder, exist_ok=True)

    folders = [
        os.path.join(source_folder, name) for name in os.listdir(source_folder) if os.path.isdir(os.path.join(source_folder, name))
    ]

    for folder in folders:
        shutil.move(folder, destination_folder)

    return destination_folder


async def post_art_poster(user:dict, meta:dict):
    """
    Args:
        markup: buttons if needed
    Returns:
        Message
    """
    photo = meta['cover']
    if meta['type'] == 'album':
        caption = await format_string(lang.s.ALBUM_TEMPLATE, meta, user)
    elif meta['type'] == 'artist':
        caption = await format_string(lang.s.ARTIST_TEMPLATE, meta, user)
    else:
        caption = await format_string(lang.s.PLAYLIST_TEMPLATE, meta, user)
    
    _, art_poster, __ = fetch_zip_settings(user)
    if art_poster:
        msg = await send_message(user, photo, 'pic', caption)
        return msg


# --- MODIFIKASI DIMULAI (Menambahkan Kualitas ke Caption) ---
async def create_simple_text(meta, user):
    """
    Membuat caption kustom untuk unggahan ZIP.
    Mengabaikan template bahasa untuk memastikan format konsisten.
    """
    # Ambil data dengan nilai default jika tidak ada
    name = meta.get('title', 'N/A')
    type_ = meta.get('type', 'N/A').title()
    provider = meta.get('provider', 'N/A')
    quality = meta.get('quality', 'N/A') # <- Kita ambil kualitasnya

    # Format caption baru
    caption_lines = [
        f"NAME : {name}",
        f"TYPE : {type_}",
        f"PROVIDER : {provider}",
        f"QUALITY : {quality}" # <-- Baris baru ditambahkan
    ]
    
    return "\n".join(caption_lines)
# --- MODIFIKASI SELESAI ---


async def edit_art_poster(metadata, user, r_link, i_link, caption):
    """
    Edits Album/Playlist Art Poster with given information
    Args:
        metadata: metadata dict of item
        caption: text to edit
    """
    markup = links_button(r_link, i_link)
    await edit_message(
        metadata['poster_msg'],
        caption,
        markup
    )


async def post_simple_message(user, meta, r_link=None, i_link=None):
    """
    Sends a simple message of item with button
    Args:
        user: user details
        meta: metadata
        markup: buttons if needed
    Returns:
        Message
    """
    caption = await create_simple_text(meta, user)
    markup = links_button(r_link, i_link)
    await send_message(user, caption, markup=markup)


async def progress_message(done, total, details):
    """
    Args:
        done: how much task done
        total: total number of tasks
        details: Message, text (dict)
    """
    progress_bar = "{0}{1}".format(
        ''.join(["▰" for i in range(math.floor((done/total) * 10))]),
        ''.join(["▱" for i in range(10 - math.floor((done/total) * 10))])
    )

    try:
        await edit_message(
            details['msg'],
            details['text'].format(
                progress_bar, 
                done, 
                total, 
                details['title'],
                details['type'].title()
            ),
            None,
            False
        )
    except FloodWait as e:
        pass


async def cleanup(user=None, metadata=None, user_dict: dict=None):
    """
    Clean up after task completed - For concurrent downloads
    Clean up after upload - For single download
    
    if metadata
        Artist/Album/Playlist files are deleted
    if user
        user root folder is removed
    
    """
    if metadata:
        # --- PERBAIKAN: Logika cleanup disederhanakan ---
        try:
            # 1. Hapus 'folderpath'. Cek apakah itu string (logika baru) atau list (logika Qobuz lama)
            folder_path = metadata.get('folderpath')
            if isinstance(folder_path, str) and os.path.isdir(folder_path):
                # Ini adalah path direktori (logika baru), hapus direktorinya
                shutil.rmtree(folder_path)
            elif isinstance(folder_path, list):
                # Ini adalah list file zip (logika Qobuz lama), hapus setiap file
                LOGGER.debug("Cleanup: 'folderpath' adalah list (logika lama). Menghapus file di list.")
                for i in folder_path:
                    if os.path.exists(i):
                        os.remove(i)

            # 2. Jika 'zip_path' ada (logika baru), hapus file-file zip itu juga.
            if metadata.get('zip_path'):
                zip_files = metadata['zip_path']
                if isinstance(zip_files, str):
                    zip_files = [zip_files] # Buat jadi list
                
                for zip_file_path in zip_files:
                    if os.path.exists(zip_file_path):
                        os.remove(zip_file_path) # os.remove() benar untuk file zip

        except FileNotFoundError:
            pass
        except Exception as e:
            LOGGER.error(f"Error saat cleanup metadata: {e}")
        # --- AKHIR PERBAIKAN ---

    if user:
        try:
            shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
        except FileNotFoundError:
            pass
        except Exception as e:
            LOGGER.info(e)
        try:
            shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/")
        except FileNotFoundError:
            pass
        except Exception as e:
            LOGGER.info(e)

def fetch_zip_settings(users: typing.Dict) -> typing.Union[bool, bool, bool]:
    """
    Args: Users (typing.Dict)
    
    Returns:
      bool (playlist_zip, art_poster, album_zip)
    """
    #import logging
    playlist_zip, art_poster, album_zip = [False] * 3
    
    user_dict = bot_set.user_data.get(users.get("user_id", 0), {})
    playlist_zip = user_dict.get("playlist_zip", bot_set.playlist_zip)
    art_poster = user_dict.get("art_poster", bot_set.art_poster)
    album_zip = user_dict.get("album_zip", bot_set.album_zip)
    #logging.info((user_dict))
    return playlist_zip, art_poster, album_zip
