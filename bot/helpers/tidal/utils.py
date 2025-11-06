# [GANTI FILE: bot/helpers/tidal/utils.py]

import re
import os
import aiofiles
import asyncio
import logging

from shutil import copyfileobj
from xml.etree import ElementTree

# --- MODIFIKASI: Impor manajer baru ---
from .manager import tidal_manager
# Kita juga butuh Tipe data TidalApi
try:
    from .tidal_api import TidalApi
except ImportError:
    class TidalApi: pass # Fallback
# --- MODIFIKASI SELESAI ---


async def parse_url(url):
    """
    Parse url type and ID from Tidal URL
    Args:
        url (str): Tidal URL.
    Returns:
        id: int
        type: str
    """
    patterns = [
        (r"/browse/track/(\d+)", "track"),  # Track from browse
        (r"/browse/artist/(\d+)", "artist"),  # Artist from browse
        (r"/browse/album/(\d+)", "album"),  # Album from browse
        (r"/browse/playlist/([\w-]+)", "playlist"),  # Playlist with numeric or UUID
        (r"/track/(\d+)", "track"),  # Track from listen.tidal.com
        (r"/artist/(\d+)", "artist"),  # Artist from listen.tidal.com
        (r"/playlist/([\w-]+)", "playlist"),  # Playlist with numeric or UUID
        (r"/album/\d+/track/(\d+)", "track"),  # Extract only track ID from album_and_track
        (r"/album/(\d+)", "album"),
    ]
    
    for pattern, type_ in patterns:
        match = re.search(pattern, url)
        if match:
            #return {"type": type_, "id": match.group(1)}
            return match.group(1), type_
    
    return None, None


async def get_stream_session(track_data: dict, user: dict):
    """
    Session needed for the quality chosen
    Args:
        track_data: raw data for the track
        user: user dict (harus berisi 'tidal_api')
    Returns:
        session: TidalSession
        quality: LOW | HIGH | LOSSLESS | HI_RES | HI_RES_LOSSLESS
    """
    media_tags = track_data['mediaMetadata']['tags']
    formats = None

    # --- MODIFIKASI: Gunakan manager dan klien yang diinjeksi ---
    if 'tidal_api' not in user:
        raise ValueError("User dict tidak memiliki 'tidal_api' client instance.")
    
    client: TidalApi = user['tidal_api']
    
    # Dapatkan pengaturan dari manager, bukan dari 'tidalapi' global
    user_dict = tidal_manager.user_data.get(user["user_id"], {})
    qual = user_dict.get("tidal_qual", tidal_manager.quality)
    spatial = user_dict.get("tidal_spatial", tidal_manager.spatial)
    # --- MODIFIKASI SELESAI ---

    if 'SONY_360RA' in media_tags and spatial == 'Sony 360RA':
        formats = '360ra'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC3 JOC':
        formats = 'ac3'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC4':
        formats = 'ac4'
    # let spatial audio have priority
    elif 'HIRES_LOSSLESS' in media_tags and qual == 'HI_RES':
        formats = 'flac_hires'

    # --- MODIFIKASI: Gunakan instance klien ---
    session = {
            'flac_hires': client.mobile_hires,
            '360ra': client.mobile_hires if client.mobile_hires else client.mobile_atmos,
            'ac4': client.mobile_atmos,
            'ac3': client.tv_session,
            None: client.tv_session,
    }[formats]

    # tv sesion gets atmos always so try mobi1e session if exists
    if not formats and 'DOLBY_ATMOS' in media_tags:
        if client.mobile_hires:
            session = client.mobile_hires
    # --- MODIFIKASI SELESAI ---

    quality = qual if formats != 'flac_hires' else 'HI_RES_LOSSLESS'
    #logging.info((session, quality))
    return session, quality
    


def parse_mpd(xml: bytes) -> list:
    xml = xml.decode('UTF-8')
    # Removes default namespace definition, don't do that!
    xml = re.sub(r'xmlns="[^"]+"', '', xml, count=1)
    root = ElementTree.fromstring(xml)

    # List of AudioTracks
    tracks = []

    for period in root.findall('Period'):
        for adaptation_set in period.findall('AdaptationSet'):
            for rep in adaptation_set.findall('Representation'):
                # Check if representation is audio
                content_type = adaptation_set.get('contentType')
                if content_type != 'audio':
                    raise ValueError('Only supports audio MPDs!')

                # Codec checks
                codec = rep.get('codecs').upper()
                if codec.startswith('MP4A'):
                    codec = 'AAC'

                # Segment template
                seg_template = rep.find('SegmentTemplate')
                # Add init file to track_urls
                track_urls = [seg_template.get('initialization')]
                start_number = int(seg_template.get('startNumber') or 1)

                # https://dashif-documents.azurewebsites.net/Guidelines-TimingModel/master/Guidelines-TimingModel.html#addressing-explicit
                # Also see example 9
                seg_timeline = seg_template.find('SegmentTimeline')
                if seg_timeline is not None:
                    seg_time_list = []
                    cur_time = 0

                    for s in seg_timeline.findall('S'):
                        # Media segments start time
                        if s.get('t'):
                            cur_time = int(s.get('t'))

                        # Segment reference
                        for i in range((int(s.get('r') or 0) + 1)):
                            seg_time_list.append(cur_time)
                            # Add duration to current time
                            cur_time += int(s.get('d'))

                    # Create list with $Number$ indices
                    seg_num_list = list(range(start_number, len(seg_time_list) + start_number))
                    # Replace $Number$ with all the seg_num_list indices
                    track_urls += [seg_template.get('media').replace('$Number$', str(n)) for n in seg_num_list]

                tracks.append(track_urls)

    return tracks, codec


async def merge_tracks(temp_tracks: list, output_path: str):
    async with aiofiles.open(output_path, 'wb') as dest_file:
        for temp_location in temp_tracks:
            async with aiofiles.open(temp_location, 'rb') as segment_file:
                while True:
                    chunk = await segment_file.read(1024 * 64)  # Read in chunks
                    if not chunk:
                        break
                    await dest_file.write(chunk)
    
    # Delete temp files asynchronously
    delete_tasks = [asyncio.to_thread(os.remove, temp_location) for temp_location in temp_tracks]
    await asyncio.gather(*delete_tasks)

async def get_quality(stream_data: dict):
    quality_dict = qualities = {
        'LOW':'LOW',
        'HIGH':'HIGH',
        'LOSSLESS':'LOSSLESS',
        'HI_RES':'MAX',
        'HI_RES_LOSSLESS':'MAX'
    }

    if stream_data['audioMode'] == 'DOLBY_ATMOS':
        return 'DOLBY ATMOS'
    return quality_dict[stream_data['audioQuality']]


async def sort_album_from_artist(album_data: dict, user: dict):
    albums = []
    
    # --- MODIFIKASI: Gunakan manager untuk pengaturan ---
    user_dict = tidal_manager.user_data.get(user["user_id"], {})
    spatial = user_dict.get("tidal_spatial", tidal_manager.spatial)
    # --- MODIFIKASI SELESAI ---

    for album in album_data:
        # --- MODIFIKASI: Gunakan variabel spasial ---
        if album['audioModes'] == ['DOLBY_ATMOS'] \
            and spatial in ['ATMOS AC3 JOC', 'ATMOS AC4']: 
            albums.append(album)
        elif album['audioModes'] == ['STEREO'] \
            and spatial == 'OFF':
            albums.append(album)
        # --- MODIFIKASI SELESAI ---

    unique_albums = {}

    # Get unique albums (check by mediaMetadata and choose one with more quality)
    for album in albums:
        unique_key = (album['title'], album['version'])

        if unique_key not in unique_albums:
            unique_albums[unique_key] = album
        else:
            existing_metadata = unique_albums[unique_key].get('mediaMetadata', {})
            new_metadata = album.get('mediaMetadata', {})
            if len(new_metadata) > len(existing_metadata):  
                unique_albums[unique_key] = album

    filtered_tracks = list(unique_albums.values())

    return filtered_tracks


async def ffmpeg_convert(input_file):
    # --- PERBAIKAN: Escape karakter $ untuk shell ---
    input_file_escaped = input_file.replace("$", "\\$")
    cmd = f'ffmpeg -i "{input_file_escaped}" -c:a copy -loglevel error -y "{input_file_escaped}.flac"'
    # --- AKHIR PERBAIKAN ---
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
