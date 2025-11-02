import subprocess
import traceback
import shutil
import os
import json
import asyncio
import tempfile
import time
import shutil
from pathlib import Path
from typing import Dict, List, Optional


from config import Config
from bot.logger import LOGGER
from bot.helpers.message import send_message, edit_message
from ..uploder import track_upload, album_upload
from ..metadata import set_metadata

current_directory = Path(__file__).resolve().parent
orpheus_dir = Path(__file__).resolve().parent.parent / "OrpheusDL"
orpheusdl_config_path = orpheus_dir / "config" / "settings.json"
orpheusdl_dir = orpheus_dir / "Download"

def beatport_login():
    with open(orpheusdl_config_path, "r") as f:
        config = json.load(f)
    config["global"]["general"]["download_path"] = str(orpheusdl_dir)
    config["modules"]["beatport"]["username"] = Config.BEATPORT_USERNAME
    config["modules"]["beatport"]["password"] = Config.BEATPORT_PASSWORD
    with open(orpheusdl_config_path, "w") as f:
        json.dump(config, f, indent=4)
    
    global album_meta
    global track_meta
    album_meta = {}
    track_meta = {}
    LOGGER.info("created album_meta and track_meta dictionaries")

async def start_beatport(url:str, user:dict):
    user_id = user['r_id']
    user_temp_dir = Path(tempfile.mkdtemp(prefix=f"{user_id}")) / "Beatport"
    LOGGER.info(f"download task ready for {user_id}")
    try:
        with open(orpheusdl_config_path, "r") as f:
            original_settings = json.load(f)
        
        user_settings = original_settings.copy()
        user_settings["global"]["general"]["download_path"] = str(user_temp_dir)
        
        # with open(user_temp_config_path, "w") as f:
        #         json.dump(user_settings, f, indent=4)
            
        with tempfile.TemporaryDirectory() as tmpdir:
            global user_temp_config
            global user_temp_config_path
            user_temp_config = f"{user_id}_settings.json"
            user_temp_config_path = os.path.join(tmpdir, user_temp_config)

            with open(user_temp_config_path, "w") as f:
                json.dump(user_settings, f, indent=4)
            
            os.chdir(orpheus_dir)
            os.symlink(orpheusdl_config_path, user_temp_config_path)
            LOGGER.info(f"created user config symlink for {user_id}")
        
            try:
                subprocess.run(["python", "orpheus.py", url])
                LOGGER.info(f"Orpheusdl executed for {user_id}")
            finally:
                os.chdir(current_directory)
            
        music_files = os.listdir(user_temp_dir)
        music_files = [f for f in music_files]
        music_files_number = len(music_files)
        if musie_files_number == 1:
            track_meta["filepath"] = Path(music_files[0]).resolve()
            await track_upload(track_meta, user, disable_link)
            lOGGER.info(f"uploaded track for user {user_id}")
        elif music_files_number > 1:
            album_meta["folderpath"] = Path(music_files[0]).resolve().parent
            await album_upload(album_meta, user)
            LOGGER.info(f"uploaded album for user {user_id}")
    
    except Exception as e:
        LOGGER.info(f"error occurred for user {user_id}, {e}")
    
    finally:
        with open (orpheusdl_config_path, "w") as f:
            json.dump(original_settings, f, indent=4)
        
        if user_temp_dir.exists():
            shutil.rmtree(user_temp_dir)
        LOGGER.info(f"cleaned up temp files for user {user_id}")

        