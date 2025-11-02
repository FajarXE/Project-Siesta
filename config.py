import os
import logging
import sys
from os import getenv
from dotenv import load_dotenv

if not os.environ.get("ENV"):
    load_dotenv('.env', override=True)

def _validate_database_name(db_name: str) -> bool:
    """Validate MongoDB database name according to MongoDB rules"""
    if not db_name:
        return False
    
    # Database names cannot contain: '/', '\', ' ', '.', '"', '*', '<', '>', ':', '|', '?'
    invalid_chars = ['/', '\\', ' ', '.', '"', '*', '<', '>', ':', '|', '?']
    
    for char in invalid_chars:
        if char in db_name:
            return False
    
    # Cannot be empty string
    if not db_name.strip():
        return False
    
    # Cannot be null
    if db_name.lower() == 'null':
        return False
    
    return True

class Config:
#--------------------

# MAIN BOT VARIABLES

#--------------------
    try:
        TG_BOT_TOKEN = getenv("TG_BOT_TOKEN")
        if not TG_BOT_TOKEN or TG_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("TG_BOT_TOKEN is not set in .env file. Get it from @BotFather on Telegram.")

        APP_ID = getenv("APP_ID")
        if not APP_ID or APP_ID == "YOUR_APP_ID_HERE":
            raise ValueError("APP_ID is not set in .env file. Get it from https://my.telegram.org/apps")
        APP_ID = int(APP_ID)

        API_HASH = getenv("API_HASH")
        if not API_HASH or API_HASH == "YOUR_API_HASH_HERE":
            raise ValueError("API_HASH is not set in .env file. Get it from https://my.telegram.org/apps")

        # MongoDB configuration - separate URI and database name
        MONGODB_URI = getenv("MONGODB_URI")
        MONGODB_DB = getenv("MONGODB_DB")
        
        # Support legacy DATABASE_URL for backward compatibility
        DATABASE_URL = getenv("DATABASE_URL")
        
        if DATABASE_URL and not MONGODB_URI:
            # Legacy mode: extract URI and DB from DATABASE_URL
            MONGODB_URI = DATABASE_URL
            # Extract database name from URI if present
            if '/' in DATABASE_URL.rsplit(':', 1)[-1]:
                # Remove the database part from URI and use as DB name
                parts = DATABASE_URL.rsplit('/', 1)
                MONGODB_URI = parts[0] + '/'
                MONGODB_DB = parts[1]
                LOGGER.warning("CONFIG: Using legacy DATABASE_URL format. Please migrate to MONGODB_URI and MONGODB_DB for better validation.")
        
        if not MONGODB_URI:
            raise ValueError("MONGODB_URI is not set in .env file. Example: mongodb://localhost:27017/")
        
        if not MONGODB_DB:
            raise ValueError("MONGODB_DB is not set in .env file. Example: siesta_bot")
        
        # Validate database name
        if not _validate_database_name(MONGODB_DB):
            raise ValueError(f"Invalid database name '{MONGODB_DB}'. Database names cannot contain '/', '\\', ' ', '.', '\"', '*', '<', '>', ':', '|', '?', or start with '.'. Please set MONGODB_DB to a simple name like 'siesta_bot'")
        
        # Set DATABASE_URL for backward compatibility with existing code
        DATABASE_URL = MONGODB_URI

        BOT_USERNAME = getenv("BOT_USERNAME")
        if not BOT_USERNAME or BOT_USERNAME == "YOUR_BOT_USERNAME_HERE":
            raise ValueError("BOT_USERNAME is not set in .env file.")
        BOT_USERNAME = BOT_USERNAME.lstrip("@")

        ADMINS_STR = getenv("ADMINS")
        if not ADMINS_STR or ADMINS_STR == "YOUR_TELEGRAM_USER_ID_HERE":
            raise ValueError("ADMINS is not set in .env file. Add your Telegram User ID.")
        ADMINS = set(int(x) for x in ADMINS_STR.split())

        PORT = getenv("PORT", "0")
        if PORT.isdigit():
            PORT = int(PORT)
    except ValueError as e:
        logging.error(f"\n{'='*60}\nCONFIGURATION ERROR\n{'='*60}\n{e}\n\nPlease check your .env file and ensure all required values are set.\nSee SETUP_GUIDE.md for detailed instructions.\n{'='*60}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"\n{'='*60}\nCONFIGURATION ERROR\n{'='*60}\nBOT : Essential Configs are missing or invalid -> {e}\n\nPlease check your .env file and ensure all required values are set.\nSee SETUP_GUIDE.md for detailed instructions.\n{'='*60}")
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

# PYROGRAM SESSION CONFIGURATION

#--------------------
    # Session configuration to prevent AUTH_KEY_DUPLICATED
    SESSION_NAME = getenv("SESSION_NAME", "siesta")
    SESSION_DIR = getenv("SESSION_DIR", "/data/sessions")
    # Full session path will be os.path.join(SESSION_DIR, SESSION_NAME)

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
    QOBUZ_EMAIL = getenv("QOBUZ_EMAIL", None)
    QOBUZ_PASSWORD = getenv("QOBUZ_PASSWORD", None)
    QOBUZ_USER = getenv("QOBUZ_USER", None)
    QOBUZ_TOKEN = getenv("QOBUZ_TOKEN", None)
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

    # Add Beatport configuration
    BEATPORT_USERNAME = getenv("BEATPORT_USERNAME", None)
    BEATPORT_PASSWORD = getenv("BEATPORT_PASSWORD", None)

    # OrpheusDL settings
    ORPHEUSDL_TIMEOUT = int(getenv("ORPHEUSDL_TIMEOUT", "3600"))  # 1 hour default
#--------------------    
    
# CONCURRENT

#--------------------
    MAX_WORKERS = int(getenv("MAX_WORKERS", "15"))