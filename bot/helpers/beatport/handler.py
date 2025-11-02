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
from threading import Lock

from config import Config
from bot.logger import LOGGER
from bot.helpers.message import send_message, edit_message
from ..uploder import track_upload, album_upload
from ..metadata import set_metadata

current_directory = Path(__file__).resolve().parent
orpheusdl_main_dir = Path(__file__).resolve().parent.parent / "OrpheusDL"
orpheusdl_main_config_path = orpheusdl_main_dir / "config" / "settings.json"

# Thread-safe lock for creating user instances
instance_lock = Lock()

def beatport_login():
    """Initialize base Beatport configuration in main OrpheusDL instance"""
    with instance_lock:
        # Ensure main config directory exists
        orpheusdl_main_config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Read or create main config
        if orpheusdl_main_config_path.exists():
            with open(orpheusdl_main_config_path, "r") as f:
                config = json.load(f)
        else:
            config = {
                "global": {
                    "general": {
                        "download_path": str(orpheusdl_main_dir / "Download")
                    }
                },
                "modules": {
                    "beatport": {}
                }
            }
        
        # Update Beatport credentials
        config["modules"]["beatport"]["username"] = Config.BEATPORT_USERNAME
        config["modules"]["beatport"]["password"] = Config.BEATPORT_PASSWORD
        
        with open(orpheusdl_main_config_path, "w") as f:
            json.dump(config, f, indent=4)
    
    LOGGER.info("Base Beatport configuration completed")

async def start_beatport(url: str, user: dict):
    user_id = user['r_id']
    
    # Create unique temp directory for this user session
    user_temp_root = Path(tempfile.mkdtemp(prefix=f"beatport_{user_id}_"))
    user_download_dir = user_temp_root / "downloads"
    user_download_dir.mkdir(parents=True, exist_ok=True)
    
    LOGGER.info(f"Beatport download task started for user {user_id}, temp dir: {user_temp_root}")
    
    # Create isolated OrpheusDL instance for this user
    user_orpheus_dir = user_temp_root / "OrpheusDL"
    
    try:
        # Copy main OrpheusDL files to user instance (without downloads)
        await create_user_orpheus_instance(user_orpheus_dir, user_download_dir, user_id)
        
        # Run OrpheusDL from user's isolated instance
        await run_user_orpheus(user_orpheus_dir, url, user_id)
        
        # Process downloaded files
        await process_downloaded_files(user_download_dir, user_id, user)
        
    except Exception as e:
        LOGGER.error(f"Error in Beatport download for user {user_id}: {e}")
        LOGGER.error(traceback.format_exc())
        raise
    finally:
        # Clean up temp directory
        await cleanup_temp_directory(user_temp_root, user_id)

async def create_user_orpheus_instance(user_orpheus_dir: Path, user_download_dir: Path, user_id: str):
    """Create an isolated OrpheusDL instance for the user"""
    LOGGER.info(f"Creating isolated OrpheusDL instance for user {user_id}")
    
    # Copy OrpheusDL structure (excluding large directories)
    ignore_patterns = shutil.ignore_patterns(
        '__pycache__', '*.pyc', '.git', 'downloads', 'Download', 'temp', 'tmp'
    )
    
    shutil.copytree(
        orpheusdl_main_dir, 
        user_orpheus_dir, 
        ignore=ignore_patterns,
        dirs_exist_ok=True
    )
    
    # Create user-specific config
    user_config_path = user_orpheus_dir / "config" / "settings.json"
    user_config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Read base config
    with open(orpheusdl_main_config_path, "r") as f:
        user_config = json.load(f)
    
    # Update with user-specific paths
    user_config["global"]["general"]["download_path"] = str(user_download_dir)
    
    # Write user config
    with open(user_config_path, "w") as f:
        json.dump(user_config, f, indent=4)
    
    LOGGER.info(f"Created isolated OrpheusDL instance for user {user_id} at {user_orpheus_dir}")

async def run_user_orpheus(user_orpheus_dir: Path, url: str, user_id: str):
    """Run OrpheusDL from user's isolated instance"""
    original_cwd = os.getcwd()
    
    try:
        # Change to user's OrpheusDL directory
        os.chdir(user_orpheus_dir)
        
        LOGGER.info(f"Running OrpheusDL for user {user_id} from {user_orpheus_dir}")
        LOGGER.info(f"Download URL: {url}")
        
        # Run OrpheusDL with user's isolated instance
        result = subprocess.run([
            "python", "orpheus.py", url
        ], 
        check=True,
        capture_output=True,
        text=True,
        timeout=300  # 5 minute timeout
        )
        
        LOGGER.info(f"OrpheusDL completed for user {user_id}")
        if result.stdout:
            LOGGER.debug(f"OrpheusDL stdout: {result.stdout}")
        if result.stderr:
            LOGGER.warning(f"OrpheusDL stderr: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        LOGGER.error(f"OrpheusDL timeout for user {user_id}")
        raise Exception("Download timeout - please try again")
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"OrpheusDL failed for user {user_id}: {e}")
        LOGGER.error(f"Error output: {e.stderr}")
        raise Exception(f"Download failed: {e.stderr}")
    finally:
        os.chdir(original_cwd)

async def process_downloaded_files(download_dir: Path, user_id: str, user: dict):
    """Process downloaded music files"""
    if not download_dir.exists():
        LOGGER.warning(f"No download directory found for user {user_id}")
        raise Exception("Download directory not found")
    
    # Find all music files recursively
    music_files = []
    music_extensions = ['.mp3', '.flac', '.m4a', '.wav', '.aac', '.ogg']
    
    for ext in music_extensions:
        music_files.extend(list(download_dir.rglob(f"*{ext}")))
    
    # Also look in subdirectories for organized downloads
    for item in download_dir.rglob('*'):
        if item.is_file() and item.suffix.lower() in music_extensions:
            if item not in music_files:
                music_files.append(item)
    
    music_files_number = len(music_files)
    LOGGER.info(f"Found {music_files_number} music files for user {user_id}")
    
    if music_files_number == 0:
        LOGGER.warning(f"No music files found for user {user_id}")
        # List all files for debugging
        all_files = list(download_dir.rglob('*'))
        LOGGER.info(f"All files in download dir: {[str(f) for f in all_files]}")
        raise Exception("No music files were downloaded")
    
    elif music_files_number == 1:
        # Single track
        track_meta = {
            "filepath": music_files[0],
            "title": music_files[0].stem,
            "user_id": user_id
        }
        await track_upload(track_meta, user, disable_link=False)
        LOGGER.info(f"Uploaded single track for user {user_id}")
        
    else:
        # Album or multiple tracks
        # Find the common parent directory for all files
        common_parent = find_common_parent(music_files)
        
        album_meta = {
            "folderpath": common_parent,
            "title": common_parent.name,
            "user_id": user_id
        }
        await album_upload(album_meta, user)
        LOGGER.info(f"Uploaded album with {music_files_number} tracks for user {user_id}")

def find_common_parent(file_paths: List[Path]) -> Path:
    """Find the common parent directory for all files"""
    if not file_paths:
        raise ValueError("No files provided")
    
    common_parent = file_paths[0].parent
    for file_path in file_paths[1:]:
        # Find common parent by comparing path components
        common_parts = []
        for part1, part2 in zip(common_parent.parts, file_path.parent.parts):
            if part1 == part2:
                common_parts.append(part1)
            else:
                break
        common_parent = Path(*common_parts)
    
    return common_parent

async def cleanup_temp_directory(temp_dir: Path, user_id: str):
    """Clean up temporary directory with error handling"""
    if temp_dir.exists():
        max_retries = 3
        for attempt in range(max_retries):
            try:
                shutil.rmtree(temp_dir)
                LOGGER.info(f"Cleaned up temp directory for user {user_id}: {temp_dir}")
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    LOGGER.error(f"Failed to clean up temp directory for user {user_id} after {max_retries} attempts: {e}")
                else:
                    LOGGER.warning(f"Retry {attempt + 1} for cleaning temp directory for user {user_id}: {e}")
                    await asyncio.sleep(1)  # Wait before retry