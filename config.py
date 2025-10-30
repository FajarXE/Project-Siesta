import os
import logging
import sys
from os import getenv
from dotenv import load_dotenv

if not os.environ.get("ENV"):
    load_dotenv('.env', override=True)

class Config:
#--------------------

# MAIN BOT VARIABLES

#--------------------
    try:
        TG_BOT_TOKEN = getenv("TG_BOT_TOKEN")
        APP_ID = int(getenv("APP_ID"))
        API_HASH = getenv("API_HASH")
        DATABASE_URL = getenv("DATABASE_URL")
        BOT_USERNAME = getenv("BOT_USERNAME").lstrip("@")
        ADMINS = set(int(x) for x in getenv("ADMINS").split())
        PORT = getenv("PORT", "0")
        if PORT.isdigit():
            PORT = int(PORT)
    except Exception as e:
        logging.warning(f"BOT : Essential Configs are missing -> {e}")
        sys.exit(1)


#--------------------

# BOT WORKING DIRECTORY

#--------------------
    # For pyrogram temp files
    WORK_DIR = getenv("WORK_DIR", "./bot/")
    # Just name of the Downloads Folder
    DOWNLOADS_FOLDER = getenv("DOWNLOADS_FOLDER", "DOWNLOADS")
    DOWNLOAD_BASE_DIR = WORK_DIR + DOWNLOADS_FOLDER
    LOCAL_STORAGE = getenv("LOCAL_STORAGE", DOWNLOAD_BASE_DIR)
#--------------------

# FILE/FOLDER NAMING

#--------------------
    PLAYLIST_NAME_FORMAT = getenv("PLAYLIST_NAME_FORMAT", "{title} - Playlist")
    #ALBUM_NAME_FORMAT = getenv("ALBUM_PATH_FORMAT", "{album} - {albumartist}")
    TRACK_NAME_FORMAT = getenv("TRACK_NAME_FORMAT", "{title} - {artist}")
#--------------------

# RCLONE / INDEX

#--------------------
    RCLONE_CONFIG = getenv("RCLONE_CONFIG", None)
    # No trailing slashes '/' for both index and rclone_dest
    RCLONE_DEST = getenv("RCLONE_DEST", 'remote:newfolder')
    INDEX_LINK = getenv('INDEX_LINK', None)
#--------------------

# QOBUZ
#--------------------
    
    # MODIFIKASI: Semua variabel Qobuz lama dihapus
    # dan diganti dengan loop pintar di bawah ini.

    QOBUZ_ACCOUNTS = []
    i = 1
    while True:
        # 1. Mencari akun berdasarkan User/Token
        user_id = getenv(f"QOBUZ_USER_{i}")
        user_token = getenv(f"QOBUZ_TOKEN_{i}")
        
        # 2. ATAU mencari akun berdasarkan Email/Password
        email = getenv(f"QOBUZ_EMAIL_{i}")
        password = getenv(f"QOBUZ_PASSWORD_{i}")

        account_data = {}
        if user_id and user_token:
            logging.info(f"Ditemukan Qobuz Akun #{i} (User/Token)")
            account_data = {"user_id": user_id, "user_token": user_token}
        elif email and password:
            logging.info(f"Ditemukan Qobuz Akun #{i} (Email/Pass)")
            account_data = {"email": email, "password": password}
        else:
            # 3. Jika tidak ada lagi akun (misal QOBUZ_USER_3 tidak ada),
            #    loop akan berhenti.
            if i > 1: # Hanya tampilkan log jika setidaknya satu akun ditemukan
                 logging.info(f"Selesai memuat {i-1} akun Qobuz.")
            break
        
        account_data["id"] = i # Simpan ID unik (1, 2, 3...)
        QOBUZ_ACCOUNTS.append(account_data)
        i += 1
    
    if not QOBUZ_ACCOUNTS:
        logging.warning("Tidak ada kredensial Qobuz (QOBUZ_USER_1, dll.) ditemukan di .env")

#--------------------

# DEEZER

#--------------------
    DEEZER_EMAIL = getenv("DEEZER_EMAIL", None)
    DEEZER_PASSWORD = getenv("DEEZER_PASSWORD", None)
    DEEZER_BF_SECRET = getenv("DEEZER_BF_SECRET", None)
    #DEEZER_TRACK_URL_KEY = getenv("DEEZER_TRACK_URL_KEY", None)
    DEEZER_ARL = getenv("DEEZER_ARL", None)
#--------------------

# TIDAL

#--------------------
    ENABLE_TIDAL = getenv("ENABLE_TIDAL", None)
    TIDAL_MOBILE = getenv("TIDAL_MOBILE", None) # only use email pass in mobile session
    TIDAL_MOBILE_TOKEN = getenv("TIDAL_MOBILE_TOKEN", None)
    TIDAL_ATMOS_MOBILE_TOKEN = getenv("TIDAL_ATMOS_MOBILE_TOKEN", None)
    TIDAL_TV_TOKEN = getenv("TIDAL_TV_TOKEN", None)
    TIDAL_TV_SECRET = getenv("TIDAL_TV_SECRET", None)
    TIDAL_CONVERT_M4A = getenv("TIDAL_CONVERT_M4A", False)
    TIDAL_REFRESH_TOKEN = getenv("TIDAL_REFRESH_TOKEN", None)
    TIDAL_COUNTRY_CODE = getenv("TIDAL_COUNTRY_CODE", None) # example CA for Canada
#--------------------    
    
# CONCURRENT

#--------------------
    MAX_WORKERS = int(getenv("MAX_WORKERS", "15"))
