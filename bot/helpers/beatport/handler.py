import subprocess
import traceback
import shutil
import os
import json
import asyncio
import tempfile
import time
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
        
        LOGGER.info(f"OrpheusDLHandler initialized. OrpheusDL directory: {self.orpheusdl_dir}")
        LOGGER.info(f"Download temp directory: {self.orpheusdl_dldir}")

    def _ensure_directories(self):
        """Create necessary directories"""
        self.orpheusdl_dldir.mkdir(parents=True, exist_ok=True)
        LOGGER.debug(f"Ensured directory exists: {self.orpheusdl_dldir}")

    def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific user to prevent concurrent requests"""
        if user_id not in self.active_downloads:
            self.active_downloads[user_id] = asyncio.Lock()
            LOGGER.debug(f"Created new lock for user: {user_id}")
        return self.active_downloads[user_id]

    async def start_beatport(self, url: str, user: Dict) -> bool:
        """
        Main entry point for Beatport downloads
        Returns: Success status
        """
        user_id = user['r_id']
        LOGGER.info(f"Starting Beatport download for user {user_id}. URL: {url}")
        
        user_lock = self._get_user_lock(user_id)
        async with user_lock:
            LOGGER.debug(f"Acquired lock for user {user_id}")
            result = await self._process_beatport_request(url, user)
            LOGGER.info(f"Beatport download completed for user {user_id}. Success: {result}")
            return result

    async def _process_beatport_request(self, url: str, user: Dict) -> bool:
        """Process a single Beatport request with proper isolation"""
        user_id = user['r_id']
        user_temp_dir = None
        
        LOGGER.info(f"Processing Beatport request for user {user_id}")
        
        try:
            # Create unique temp directory for this request
            user_temp_dir = self._create_user_temp_dir(user_id)
            LOGGER.info(f"Created user temp directory: {user_temp_dir}")

            # Configure and run OrpheusDL
            LOGGER.info("Starting OrpheusDL download process...")
            success = await self._run_orpheusdl(url, user, user_temp_dir)
            
            if not success:
                LOGGER.error(f"OrpheusDL download failed for user {user_id}")
                return False

            LOGGER.info("OrpheusDL download completed successfully, processing files...")
            
            # Process and upload files
            await self._process_downloaded_files(user_temp_dir, user, url)
            
            LOGGER.info(f"File processing and upload completed for user {user_id}")
            return True

        except Exception as e:
            LOGGER.error(f"OrpheusDL processing error for user {user_id}: {traceback.format_exc()}")
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
        LOGGER.debug(f"Created user temp directory: {temp_dir}")
        return temp_dir

    async def _run_orpheusdl(self, url: str, user: Dict, temp_dir: Path) -> bool:
        """Run OrpheusDL with proper configuration and capture all output"""
        user_id = user['r_id']
        LOGGER.info(f"Running OrpheusDL for user {user_id} in directory: {temp_dir}")
        
        try:
            # Store original files to detect new downloads
            original_files = set()
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    original_files.add(Path(root) / file)
            
            LOGGER.debug(f"Found {len(original_files)} existing files in temp directory")

            # Configure OrpheusDL
            LOGGER.info("Configuring OrpheusDL settings...")
            await self._configure_orpheusdl(temp_dir)

            # Run OrpheusDL process
            LOGGER.info(f"Executing OrpheusDL with URL: {url}")
            process = await asyncio.create_subprocess_exec(
                "python3", "orpheus.py", url,
                cwd=str(self.orpheusdl_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Capture stdout and stderr in real-time
            stdout_chunks = []
            stderr_chunks = []
            
            # Read stdout and stderr concurrently
            async def read_stream(stream, chunks):
                while True:
                    chunk = await stream.read(1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
            
            await asyncio.gather(
                read_stream(process.stdout, stdout_chunks),
                read_stream(process.stderr, stderr_chunks)
            )

            # Wait for process to complete
            returncode = await process.wait()
            stdout = b"".join(stdout_chunks).decode('utf-8', errors='ignore')
            stderr = b"".join(stderr_chunks).decode('utf-8', errors='ignore')
            
            # Log OrpheusDL output
            LOGGER.info(f"OrpheusDL process completed with return code: {returncode}")
            if stdout:
                LOGGER.info(f"OrpheusDL stdout:\n{stdout}")
            if stderr:
                LOGGER.warning(f"OrpheusDL stderr:\n{stderr}")

            if returncode != 0:
                error_msg = stderr if stderr else stdout if stdout else "Unknown error"
                LOGGER.error(f"OrpheusDL process failed with return code {returncode}. Error: {error_msg}")
                await send_message(user, f"OrpheusDL error (code {returncode}): {error_msg[:500]}...")
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
                LOGGER.warning(f"No new music files downloaded for user {user_id}. Original files: {len(original_files)}")
                await send_message(user, "No music files were downloaded - possibly invalid URL or no tracks available")
                return False

            LOGGER.info(f"Downloaded {len(new_files)} new audio files for user {user_id}")
            LOGGER.debug(f"Downloaded files: {[f.name for f in new_files]}")
            return True

        except Exception as e:
            LOGGER.error(f"OrpheusDL execution error for user {user_id}: {traceback.format_exc()}")
            await send_message(user, f"Download execution failed: {str(e)}")
            return False

    async def _configure_orpheusdl(self, temp_dir: Path):
        """Configure OrpheusDL settings"""
        try:
            LOGGER.info(f"Loading OrpheusDL config from: {self.orpheusdl_json}")
            
            with open(self.orpheusdl_json, "r") as i:
                config_data = json.load(i)

            # Update configuration
            old_path = config_data["global"]["general"].get("download_path", "")
            config_data["global"]["general"]["download_path"] = str(temp_dir)
            config_data["modules"]["beatport"]["username"] = Config.BEATPORT_USERNAME
            # Don't log password, just indicate if it's set
            password_set = bool(Config.BEATPORT_PASSWORD)
            config_data["modules"]["beatport"]["password"] = Config.BEATPORT_PASSWORD

            with open(self.orpheusdl_json, "w") as o:
                json.dump(config_data, o, indent=4)

            LOGGER.info(f"Updated OrpheusDL config. Download path: {old_path} -> {temp_dir}")
            LOGGER.info(f"Beatport username configured: {Config.BEATPORT_USERNAME}")
            LOGGER.info(f"Beatport password configured: {'Yes' if password_set else 'No'}")

        except Exception as e:
            LOGGER.error(f"OrpheusDL configuration error: {traceback.format_exc()}")
            raise

    async def _process_downloaded_files(self, temp_dir: Path, user: Dict, original_url: str):
        """Process and upload downloaded files"""
        user_id = user['r_id']
        LOGGER.info(f"Processing downloaded files for user {user_id} in {temp_dir}")

        # Find all audio files
        audio_files = []
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in ['.flac', '.mp3', '.m4a', '.wav']:
                    audio_files.append(file_path)

        LOGGER.info(f"Found {len(audio_files)} audio files to process")
        
        if not audio_files:
            LOGGER.warning(f"No audio files found for user {user_id} in {temp_dir}")
            await send_message(user, "No audio files found to process")
            return

        await edit_message(user['bot_msg'], f"Processing {len(audio_files)} files for upload...")
        LOGGER.info(f"Starting metadata extraction for {len(audio_files)} files")

        # Extract metadata and upload
        music_files = []
        for file_path in audio_files:
            metadata = await self._extract_metadata_from_file(file_path, user)
            music_files.append(metadata)

        LOGGER.info(f"Metadata extraction completed. Files with metadata: {len(music_files)}")

        # Route to appropriate upload function
        if len(music_files) == 1:
            LOGGER.info("Single track detected, routing to track upload")
            await self._upload_single_track(music_files[0], user)
        else:
            LOGGER.info(f"Multiple tracks detected ({len(music_files)}), routing to album upload")
            await self._upload_multiple_tracks(music_files, user)

    async def _extract_metadata_from_file(self, file_path: Path, user: Dict) -> Dict:
        """Extract metadata from audio file"""
        user_id = user['r_id']
        LOGGER.debug(f"Extracting metadata from: {file_path.name}")
        
        try:
            # Try to use mutagen for metadata extraction
            try:
                from mutagen import File
                audio = File(file_path)
                LOGGER.debug(f"Mutagen loaded successfully for {file_path.name}")
            except ImportError:
                audio = None
                LOGGER.warning("Mutagen not available, using basic metadata extraction")

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
                LOGGER.debug(f"Audio tags available: {list(audio.keys())}")
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
                                LOGGER.debug(f"Extracted {meta_key}: {metadata[meta_key]}")
                                break
                            except (IndexError, KeyError) as e:
                                LOGGER.warning(f"Error extracting {meta_key} from tag {tag}: {e}")
                                continue

            LOGGER.info(f"Metadata extracted for {file_path.name}: {metadata['title']} by {metadata['artist']}")
            return metadata

        except Exception as e:
            LOGGER.error(f"Metadata extraction error for {file_path}: {traceback.format_exc()}")
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
        user_id = user['r_id']
        track_name = track_meta['title']
        
        LOGGER.info(f"Starting single track upload for user {user_id}: {track_name}")
        
        try:
            await edit_message(user['bot_msg'], f"Uploading: {track_name}")
            LOGGER.debug(f"Setting metadata for track: {track_name}")
            
            await set_metadata(track_meta)
            LOGGER.debug(f"Metadata set, starting track upload: {track_name}")
            
            await track_upload(track_meta, user, False)
            LOGGER.info(f"Single track upload completed: {track_name}")
            
        except Exception as e:
            LOGGER.error(f"Single track upload error for {track_name}: {traceback.format_exc()}")
            await send_message(user, f"Failed to upload {track_name}")

    async def _upload_multiple_tracks(self, music_files: List[Dict], user: Dict):
        """Upload multiple tracks as an album"""
        user_id = user['r_id']
        LOGGER.info(f"Starting multiple tracks upload for user {user_id}. Total tracks: {len(music_files)}")
        
        try:
            # Group by album
            albums = {}
            for track in music_files:
                album_key = track.get('album', 'Various Albums')
                if album_key not in albums:
                    albums[album_key] = []
                albums[album_key].append(track)

            LOGGER.info(f"Grouped tracks into {len(albums)} albums: {list(albums.keys())}")

            # Upload each album
            for album_name, tracks in albums.items():
                LOGGER.info(f"Processing album: {album_name} with {len(tracks)} tracks")
                
                if len(albums) > 1:
                    await edit_message(user['bot_msg'], f"Processing album: {album_name}")

                # Sort tracks if possible
                try:
                    tracks.sort(key=lambda x: int(x.get('tracknumber', '1').split('/')[0]))
                    LOGGER.debug(f"Sorted tracks for album: {album_name}")
                except (ValueError, AttributeError) as e:
                    LOGGER.warning(f"Could not sort tracks for album {album_name}: {e}")

                if len(tracks) == 1:
                    LOGGER.info(f"Single track in album {album_name}, using single track upload")
                    await self._upload_single_track(tracks[0], user)
                else:
                    LOGGER.info(f"Uploading album {album_name} with {len(tracks)} tracks")
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
                    LOGGER.info(f"Album upload completed: {album_name}")

            LOGGER.info(f"All albums processed for user {user_id}")

        except Exception as e:
            LOGGER.error(f"Multiple tracks upload error for user {user_id}: {traceback.format_exc()}")
            await send_message(user, f"Album upload failed: {str(e)}")

    async def _safe_cleanup(self, temp_dir: Path):
        """Safely cleanup temporary directory"""
        try:
            if temp_dir.exists():
                LOGGER.info(f"Starting cleanup of temp directory: {temp_dir}")
                # Log directory contents before cleanup
                try:
                    file_count = sum(len(files) for _, _, files in os.walk(temp_dir))
                    LOGGER.debug(f"Directory {temp_dir} contains {file_count} files before cleanup")
                except Exception as e:
                    LOGGER.warning(f"Could not count files in {temp_dir}: {e}")
                
                shutil.rmtree(temp_dir, ignore_errors=True)
                LOGGER.info(f"Successfully cleaned up temp directory: {temp_dir}")
            else:
                LOGGER.warning(f"Temp directory does not exist, skipping cleanup: {temp_dir}")
        except Exception as e:
            LOGGER.error(f"Cleanup error for {temp_dir}: {traceback.format_exc()}")


# Global instance for easy import
orpheusdl_handler = OrpheusDLHandler()
LOGGER.info("OrpheusDL handler global instance created")


# Convenience functions for external imports
async def start_orpheusdl_beatport(url: str, user: Dict) -> bool:
    """Public interface for Beatport downloads"""
    LOGGER.info(f"Public interface called for Beatport download. User: {user['r_id']}, URL: {url}")
    return await orpheusdl_handler.start_beatport(url, user)


# Background cleanup task
async def cleanup_old_downloads():
    """Clean up orphaned download directories older than 1 hour"""
    LOGGER.info("Starting background cleanup of old download directories")
    
    try:
        temp_dir = Path(tempfile.gettempdir()) / "orpheusdl_downloads"
        if not temp_dir.exists():
            LOGGER.info("Temp download directory does not exist, nothing to clean up")
            return

        cleaned_count = 0
        for item in temp_dir.iterdir():
            if item.is_dir():
                try:
                    # Extract timestamp from directory name
                    timestamp = int(item.name.split('_')[-1])
                    current_time = asyncio.get_event_loop().time() * 1000
                    if current_time - timestamp > 3600000:  # 1 hour
                        LOGGER.info(f"Cleaning up old directory: {item.name}")
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned_count += 1
                except (ValueError, IndexError):
                    # If we can't parse, delete if older than 2 hours by modification time
                    if item.stat().st_mtime < (time.time() - 7200):
                        LOGGER.info(f"Cleaning up directory with invalid name (old mtime): {item.name}")
                        shutil.rmtree(item, ignore_errors=True)
                        cleaned_count += 1

        LOGGER.info(f"Background cleanup completed. Cleaned {cleaned_count} directories")
        
    except Exception as e:
        LOGGER.error(f"Background cleanup error: {traceback.format_exc()}")