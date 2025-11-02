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

current_directory = Path(__file__).resolve().parent
orpheus_dir = Path(__file__).resolve().parent.parent / "OrpheusDL"
orpheusdl_config_path = orpheusdl_dir / "config" / "settings.json"
orpheusdl_dir = orpheusdl_dir / "Download"

def beatport_login():
    with open(orpheusdl_config_path, "r") as f:
        config = json.load(f)
    config["global"]["general"]["download_path"] = str(orpheusdl_dir)
    config["modules"]["beatport"]["username"] = Config.BEATPORT_USERNAME
    config["modules"]["beatport"]["password"] = Config.BEATPORT_PASSWORD
    with open(orpheusdl_config_path, "w") as f:
        json.dump(config, f, indent=4)
    
    album_meta = {}
    track_meta = {}
    LOGGER.info("created album_mta and track_meta dictionaries")
