# [GANTI FILE: bot/settings.py]

import os
import json
import base64
import requests
import asyncio
import logging

import bot.helpers.translations as lang

from config import Config
from bot.logger import LOGGER

from .helpers.database.mongo_async import database
# MODIFIKASI: Impor qobuz_api Dihapus
# from .helpers.qobuz.qopy import qobuz_api 

# --- MODIFIKASI: Hapus impor 'deezerapi' yang rusak ---
# from .helpers.deezer.dzapi import deezerapi
# --- BATAS MODIFIKASI ---

# --- MODIFIKASI: Impor 'tidalapi' yang rusak DIHAPUS ---
# from .helpers.tidal.tidal_api import tidalapi 
# --- MODIFIKASI SELESAI ---
from .helpers.translations import lang_available

# --- MODIFIKASI: Impor manajer baru ---
from .helpers.tidal.manager import tidal_manager
# --- MODIFIKASI SELESAI ---


def __encrypt_string__(string):
    s = bytes(string, 'utf-8')
    s = base64.b64encode(s)
    return s

def __decrypt_string__(string):
    try:
        s = base64.b64decode(string)
        s = s.decode()
        return s
    except:
        return string

loop = asyncio.new_event_loop()
set_db = loop.run_until_complete(database.get_variable())

class BotSettings:
    def __init__(self):
        # --- MODIFIKASI: self.deezer tetap False sebagai default ---
        # Ini akan diatur ke True oleh bot utama setelah manajer berhasil login.
        self.deezer = False
        # --- BATAS MODIFIKASI ---
        
        # MODIFIKASI: Atribut self.qobuz Dihapus
        # self.qobuz = False 
        
        # --- MODIFIKASI: Atribut self.tidal Dihapus ---
        # self.tidal = None 
        # --- MODIFIKASI SELESAI ---
        
        self.admins = Config.ADMINS
        self.set_db = set_db

        self.bot_lang = None
        self.auth_users = self.set_db.get('AUTH_USERS', [])
        self.auth_chats = self.set_db.get('AUTH_CHATS', [])

        self.rclone = False
        self.check_upload_mode()

        self.anti_spam = self.set_db.get('ANTI_SPAM', "OFF")

        self.bot_public = self.set_db.get('BOT_PUBLIC')

        self.art_poster = self.set_db.get('ART_POSTER')

        self.playlist_sort = self.set_db.get('PLAYLIST_SORT')
        self.disable_sort_link = self.set_db.get('PLAYLIST_LINK_DISABLE')

        self.artist_batch = self.set_db.get('ARTIST_BATCH_UPLOAD')
        self.playlist_conc = self.set_db.get('PLAYLIST_CONCURRENT')
        
        link_option = self.set_db.get('RCLONE_LINK_OPTIONS')
        self.link_options = link_option if self.rclone and link_option else 'False'

        self.album_zip = self.set_db.get('ALBUM_ZIP')
        self.playlist_zip = self.set_db.get('PLAYLIST_ZIP')
        self.artist_zip = self.set_db.get('ARTIST_ZIP')

        # --- MODIFIKASI: Hapus self.clients (tidak digunakan di sini) ---
        # self.clients = []
        # --- MODIFIKASI SELESAI ---
        
        self.user_data = {}
        
        # --- MODIFIKASI: Tambahkan variabel can_enable_tidal ---
        # Ini dibutuhkan oleh provider_settings.py untuk menampilkan tombol Login
        self.can_enable_tidal = Config.ENABLE_TIDAL
        # --- MODIFIKASI SELESAI ---


    def check_upload_mode(self):
        if os.path.exists('rclone.conf'):
            self.rclone = True
        elif Config.RCLONE_CONFIG:
            if Config.RCLONE_CONFIG.startswith('http'):
                rclone = requests.get(Config.RCLONE_CONFIG, allow_redirects=True)
                if rclone.status_code != 200:
                    LOGGER.info("RCLONE : Error retreiving file from Config URL")
                    self.rclone = False
                else:
                    with open('rclone.conf', 'wb') as f:
                        f.write(rclone.content)
                    self.rclone = True
            
        db_upload = self.set_db.get('UPLOAD_MODE')
        if self.rclone and db_upload == 'RCLONE':
            self.upload_mode = 'RCLONE'
        elif db_upload == 'Telegram' or db_upload == 'Local':
            self.upload_mode = db_upload
        else:
            self.upload_mode = 'Telegram'
    

    # MODIFIKASI: Seluruh fungsi login_qobuz(self) Dihapus
    # (Ini sekarang ditangani di __main__.py)

    # --- MODIFIKASI: Hapus seluruh fungsi 'login_deezer' ---
    # Logika ini sekarang ditangani oleh 'deezer_manager' saat startup.
    # --- BATAS MODIFIKASI ---


    # --- MODIFIKASI: Hapus seluruh fungsi 'login_tidal' ---
    # Logika ini sekarang ditangani oleh 'tidal_manager' saat startup.
    # --- BATAS MODIFIKASI ---

    
    # --- MODIFIKASI: Hapus seluruh fungsi 'save_tidal_login' ---
    # Logika ini sekarang ditangani oleh 'provider_settings.py'.
    # --- BATAS MODIFIKASI ---
        

    async def set_language(self):
        bot_lang = await database.get_variable()
        self.bot_lang = bot_lang.get("BOT_LANGUAGE", "en")
        for item in lang_available:
            logging.info(item.__language__ == self.bot_lang)
            if item.__language__ == self.bot_lang:
                lang.s = item
                break

    async def initialize_users(self) -> dict:
        user_data = await database.initialize_users()
        
        # --- MODIFIKASI: Gunakan self.deezer (bool) ---
        # Kita tidak lagi melampirkan 'user_data' ke klien di sini
        # --- BATAS MODIFIKASI ---
        
        # MODIFIKASI: Blok if self.qobuz Dihapus
        
        # --- MODIFIKASI: Muat data pengguna ke manajer ---
        # (Kita asumsikan manajer sudah diinisialisasi di __main__.py)
        if tidal_manager and tidal_manager.clients:
            tidal_manager.user_data = user_data
        # --- MODIFIKASI SELESAI ---
            
        self.user_data = user_data

bot_set = BotSettings()
