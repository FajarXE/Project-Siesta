import subprocess
import traceback
import shutil
import os
import json
import asyncio
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from bot.settings import bot_set
from bot import Config
from bot.logger import LOGGER
from bot.helpers.message import send_message, edit_message
from ..uploder import track_upload, album_upload
from ..metadata import set_metadata

class OrpheusDLHandler:
    def __init__(self):
        self.current_dir = Path(__file__).resolve().parent
        self.orpheusdl_dir = self.current_dir.parent / "OrpheusDL"
        # Use system temp directory for concurrent safety
        self.orpheusdl_dldir = Path(tempfile.gettempdir()) / "orpheusdl_downloads"
        self.orpheusdl_json = self.orpheusdl_dir / "config" / "settings.json"
        self._ensure_directories()
        self.active_downloads: Dict[str, asyncio.Lock] = {}
    
    def _ensure_directories(self):
        """Create necessary directories"""
        self.orpheusdl_dldir.mkdir(parents=True, exist_ok=True)
    
    def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific user to prevent concurrent requests"""
        if user_id not in self.active_downloads:
            self.active_downloads[user_id] = asyncio.Lock()
        return self.active_downloads[user_id]
    
    async def start_beatport(self, url: str, user: Dict) -> bool:
        """
        Main entry point for Beatport downloads
        Returns: Success status
        """
        user_lock = self._get_user_lock(user['r_id'])
        
        async with user_lock:
            return await self._process_beatport_request(url, user)
    
    async def _process_beatport_request(self, url: str, user: Dict) -> bool:
        """Process a single Beatport request with proper isolation"""
        user_temp_dir = None
        try:
            # Create unique temp directory for this request
            user_temp_dir = self._create_user_temp_dir(user['r_id'])
            
            # Configure and run OrpheusDL
            success = await self._run_orpheusdl(url, user, user_temp_dir)
            if not success:
                return False
            
            # Process and upload files
            await self._process_downloaded_files(user_temp_dir, user, url)
            return True
            
        except Exception as e:
            LOGGER.error(f"OrpheusDL processing error: {traceback.format_exc()}")
            await send_message(user, f"Download failed: {str(e)}")
            return False
        finally:
            # Always cleanup temp directory
            if user_temp_dir and user_temp_dir.exists():
                await self._safe_cleanup(user_temp_dir)
    
    def _create_user_temp_dir(self, user_id: str) -> Path:
        """Create a unique temporary directory for a user request"""
        timestamp = int(asyncio.get_event_loop().time() * 1000)  # More precise
        temp_dir = self.orpheusdl_dldir / f"{user_id}_{timestamp}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir
    
    async def _run_orpheusdl(self, url: str, user: Dict, temp_dir: Path) -> bool:
        """Run OrpheusDL with proper configuration"""
        try:
            # Store original files to detect new downloads
            original_files = set()
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    original_files.add(Path(root) / file)
            
            # Configure OrpheusDL
            await self._configure_orpheusdl(temp_dir)
            
            # Run OrpheusDL process
            process = await asyncio.create_subprocess_exec(
                "python3", "orpheus.py", url,
                cwd=str(self.orpheusdl_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                LOGGER.error(f"OrpheusDL process error: {error_msg}")
                await send_message(user, f"OrpheusDL error: {error_msg}")
                return False
            
            # Verify new files were downloaded
            new_files = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = Path(root) / file
                    if (file_path not in original_files and 
                        file_path.suffix.lower() in ['.flac', '.mp3', '.m4a', '.wav']):
                        new_files.append(file_path)
            
            if not new_files:
                await send_message(user, "No music files were downloaded")
                return False
            
            LOGGER.info(f"Downloaded {len(new_files)} files for user {user['r_id']}")
            return True
            
        except Exception as e:
            LOGGER.error(f"OrpheusDL execution error: {e}")
            await send_message(user, f"Download execution failed: {str(e)}")
            return False
    
    async def _configure_orpheusdl(self, temp_dir: Path):
        """Configure OrpheusDL settings"""
        try:
            with open(self.orpheusdl_json, "r") as i:
                config_data = json.load(i)
            
            config_data["global"]["general"]["download_path"] = str(temp_dir)
            config_data["modules"]["beatport"]["username"] = Config.BEATPORT_USERNAME
            config_data["modules"]["beatport"]["password"] = Config.BEATPORT_PASSWORD
            
            with open(self.orpheusdl_json, "w") as o:
                json.dump(config_data, o, indent=4)
                
        except Exception as e:
            LOGGER.error(f"Config error: {e}")
            raise
    
    async def _process_downloaded_files(self, temp_dir: Path, user: Dict, original_url: str):
        """Process and upload downloaded files"""
        # Find all audio files
        audio_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in ['.flac', '.mp3', '.m4a', '.wav']:
                    audio_files.append(file_path)
        
        if not audio_files:
            await send_message(user, "No audio files found to process")
            return
        
        await edit_message(user['bot_msg'], f"Processing {len(audio_files)} files for upload...")
        
        # Extract metadata and upload
        music_files = []
        for file_path in audio_files:
            metadata = await self._extract_metadata_from_file(file_path, user)
            music_files.append(metadata)
        
        # Route to appropriate upload function
        if len(music_files) == 1:
            await self._upload_single_track(music_files[0], user)
        else:
            await self._upload_multiple_tracks(music_files, user)
    
    async def _extract_metadata_from_file(self, file_path: Path, user: Dict) -> Dict:
        """Extract metadata from audio file"""
        try:
            # Try to use mutagen for metadata extraction
            try:
                from mutagen import File
                audio = File(file_path)
            except ImportError:
                audio = None
                LOGGER.warning("Mutagen not available, using basic metadata")
            
            metadata = {
                'title': file_path.stem,
                'artist': 'Unknown Artist',
                'album': 'Unknown Album',
                'albumartist': 'Unknown Artist',
                'tracknumber': '1',
                'date': '',
                'genre': '',
                'composer': '',
                'quality': 'Unknown',
                'extension': file_path.suffix.lower().lstrip('.'),
                'filepath': str(file_path),
                'provider': 'Beatport'
            }
            
            if audio is not None:
                # Extract available metadata
                tags_mapping = {
                    'title': ['title', 'titi'],
                    'artist': ['artist', 'peop', 'aART'],
                    'album': ['album', 'alb'],
                    'albumartist': ['albumartist', 'aART'],
                    'tracknumber': ['tracknumber', 'trck'],
                    'date': ['date', 'year'],
                    'genre': ['genre', 'gnre'],
                    'composer': ['composer', 'comp']
                }
                
                for meta_key, tag_keys in tags_mapping.items():
                    for tag in tag_keys:
                        if tag in audio:
                            try:
                                metadata[meta_key] = str(audio[tag][0])
                                break
                            except (IndexError, KeyError):
                                pass
            
            return metadata
            
        except Exception as e:
            LOGGER.error(f"Metadata extraction error for {file_path}: {e}")
            return {
                'title': file_path.stem,
                'artist': 'Unknown Artist',
                'album': 'Unknown Album',
                'albumartist': 'Unknown Artist',
                'quality': 'Unknown',
                'extension': file_path.suffix.lower().lstrip('.'),
                'filepath': str(file_path),
                'provider': 'Beatport'
            }
    
    async def _upload_single_track(self, track_meta: Dict, user: Dict):
        """Upload a single track"""
        try:
            await edit_message(user['bot_msg'], f"Uploading: {track_meta['title']}")
            await set_metadata(track_meta)
            await track_upload(track_meta, user, False)
        except Exception as e:
            LOGGER.error(f"Single track upload error: {e}")
            await send_message(user, f"Failed to upload {track_meta['title']}")
    
    async def _upload_multiple_tracks(self, music_files: List[Dict], user: Dict):
        """Upload multiple tracks as an album"""
        try:
            # Group by album
            albums = {}
            for track in music_files:
                album_key = track.get('album', 'Various Albums')
                if album_key not in albums:
                    albums[album_key] = []
                albums[album_key].append(track)
            
            # Upload each album
            for album_name, tracks in albums.items():
                if len(albums) > 1:
                    await edit_message(user['bot_msg'], f"Processing album: {album_name}")
                
                # Sort tracks if possible
                try:
                    tracks.sort(key=lambda x: int(x.get('tracknumber', '1').split('/')[0]))
                except (ValueError, AttributeError):
                    pass
                
                if len(tracks) == 1:
                    await self._upload_single_track(tracks[0], user)
                else:
                    album_meta = {
                        'title': album_name,
                        'artist': tracks[0].get('albumartist', tracks[0].get('artist', 'Various Artists')),
                        'tracks': tracks,
                        'type': 'album',
                        'provider': 'Beatport',
                        'quality': tracks[0].get('quality', 'Unknown'),
                        'folderpath': str(Path(tracks[0]['filepath']).parent),
                        'poster_msg': None
                    }
                    await album_upload(album_meta, user)
                    
        except Exception as e:
            LOGGER.error(f"Multiple tracks upload error: {e}")
            await send_message(user, f"Album upload failed: {str(e)}")
    
    async def _safe_cleanup(self, temp_dir: Path):
        """Safely cleanup temporary directory"""
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                LOGGER.info(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            LOGGER.error(f"Cleanup error for {temp_dir}: {e}")

# Global instance for easy import
orpheusdl_handler = OrpheusDLHandler()

# Convenience functions for external imports
async def start_orpheusdl_beatport(url: str, user: Dict) -> bool:
    """Public interface for Beatport downloads"""
    return await orpheusdl_handler.start_beatport(url, user)

# Background cleanup task
async def cleanup_old_downloads():
    """Clean up orphaned download directories older than 1 hour"""
    try:
        temp_dir = Path(tempfile.gettempdir()) / "orpheusdl_downloads"
        if temp_dir.exists():
            for item in temp_dir.iterdir():
                if item.is_dir():
                    # Extract timestamp from directory name
                    try:
                        timestamp = int(item.name.split('_')[-1])
                        current_time = asyncio.get_event_loop().time() * 1000
                        if current_time - timestamp > 3600000:  # 1 hour
                            shutil.rmtree(item, ignore_errors=True)
                    except (ValueError, IndexError):
                        # If we can't parse, delete if older than 2 hours by modification time
                        if item.stat().st_mtime < (time.time() - 7200):
                            shutil.rmtree(item, ignore_errors=True)
    except Exception as e:
        LOGGER.error(f"Background cleanup error: {e}")