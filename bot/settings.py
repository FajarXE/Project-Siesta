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
from .helpers.qobuz.qopy import qobuz_api
from .helpers.deezer.dzapi import deezerapi
from .helpers.tidal.tidal_api import tidalapi
from .helpers.translations import lang_available
from .helpers.beatport.handler import beatport_login


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
        self.deezer = False
        self.qobuz = False
        self.tidal = None
        self.admins = Config.ADMINS
        self.set_db = set_db

        self.bot_lang = None
        self.auth_users = self.set_db.get('AUTH_USERS', [])
        self.auth_chats = self.set_db.get('AUTH_CHATS', [])

        self.rclone = False
        self.check_upload_mode()

        self.anti_spam = self.set_db.get('ANTI_SPAM', "OFF")

        self.bot_public = self.set_db.get('BOT_PUBLIC')

        # post photo of album/artist
        self.art_poster = self.set_db.get('ART_POSTER')

        self.playlist_sort = self.set_db.get('PLAYLIST_SORT')
        # disable returning links for sorted playlist for cleaner chat
        self.disable_sort_link = self.set_db.get('PLAYLIST_LINK_DISABLE')

        # Multithreaded downloads
        self.artist_batch = self.set_db.get('ARTIST_BATCH_UPLOAD')
        self.playlist_conc = self.set_db.get('PLAYLIST_CONCURRENT')
        
        link_option = self.set_db.get('RCLONE_LINK_OPTIONS') #str
        self.link_options = link_option if self.rclone and link_option else 'False'

        self.album_zip = self.set_db.get('ALBUM_ZIP')
        self.playlist_zip = self.set_db.get('PLAYLIST_ZIP')
        self.artist_zip = self.set_db.get('ARTIST_ZIP')

        self.clients = []
        
        self.user_data = {}


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
    

    async def login_qobuz(self):
        if Config.QOBUZ_EMAIL or Config.QOBUZ_USER:
            try:
                await qobuz_api.login()
                self.qobuz = qobuz_api
                self.clients.append(qobuz_api)
                quality = self.set_db.get("QOBUZ_QUALITY")
                if quality:
                    bot_set.qobuz.quality = int(quality)
            except Exception as e:
                LOGGER.error(e)
    

    async def login_deezer(self):
        if Config.DEEZER_ARL or Config.DEEZER_EMAIL:
            if Config.DEEZER_BF_SECRET:
                login = await deezerapi.login()
                if login:
                    self.deezer = deezerapi
                    self.clients.append(deezerapi)
                    LOGGER.info(f"DEEZER : Subscription - {deezerapi.user['OFFER_NAME']}")
                else:
                    try:
                        await deezerapi.session.close()
                    except:
                        pass
            else:
                LOGGER.error('DEEZER : Check BF_SECRET and TRACK_URL_KEY')

    
    def beatport_initialise(self):
        beatport_login()
    
    async def login_tidal(self):
        # Check if Tidal is enabled
        self.can_enable_tidal = Config.ENABLE_TIDAL
        if not self.can_enable_tidal:
            return

        data = None
        # Refresh token in env is given preference
        if Config.TIDAL_REFRESH_TOKEN:
            data = {
                'user_id': None, 
                'refresh_token': Config.TIDAL_REFRESH_TOKEN, 
                'country_code': Config.TIDAL_COUNTRY_CODE
            }
            LOGGER.debug("TIDAL: Using refresh token from environment")
        else:
            # Try to get saved authentication data
            saved_info = self.set_db.get("TIDAL_AUTH_DATA")
            if saved_info:
                try:
                    data = json.loads(__decrypt_string__(saved_info))
                    LOGGER.debug("TIDAL: Using saved authentication data from Database")
                except Exception as e:
                    LOGGER.error(f"TIDAL: Failed to decrypt/parse saved auth data: {e}")
                    return

        if not data:
            return

        # Attempt login
        await tidalapi.login_from_saved(data)
        
        # Set audio quality
        quality = self.set_db.get('TIDAL_QUALITY')
        if quality:
            tidalapi.quality = quality
        
        # Set spatial audio
        spatial = self.set_db.get('TIDAL_SPATIAL')
        if spatial:
            tidalapi.spatial = spatial
        
        # Set instance variables
        self.tidal = tidalapi 
        self.clients.append(tidalapi)


    async def save_tidal_login(self, session):
        data = {
            "user_id" : session.user_id,
            "refresh_token" : session.refresh_token,
            "country_code" : session.country_code
        }

        txt = json.dumps(data)
        await database.set_variable("TIDAL_AUTH_DATA", __encrypt_string__(txt))
        

    async def set_language(self):
        bot_lang = await database.get_variable()
        self.bot_lang = bot_lang.get("BOT_LANGUAGE", "en")
        #logging.info(self.bot_lang)

        for item in lang_available:
            logging.info(item.__language__ == self.bot_lang)
            if item.__language__ == self.bot_lang:
                lang.s = item
                break
        #logging.info(lang.s)

    async def initialize_users(self) -> dict:
        user_data = await database.initialize_users()
        #logging.info(user_data)
        if self.deezer:
            self.deezer.user_data = user_data
        if self.qobuz:
            self.qobuz.user_data = user_data
        if self.tidal:
            self.tidal.user_data = user_data
        self.user_data = user_data

bot_set = BotSettings()