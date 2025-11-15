# [GANTI FILE: bot/helpers/tidal/utils.py]

import re
import os
import aiofiles
import asyncio
import logging

from shutil import copyfileobj
from xml.etree import ElementTree
from datetime import datetime # <-- Impor datetime

from .manager import tidal_manager
try:
    from .tidal_api import TidalApi
except ImportError:
    class TidalApi: pass 

async def parse_url(url):
    # ... (fungsi parse_url tidak berubah) ...
    patterns = [
        (r"/browse/track/(\d+)", "track"),
        (r"/browse/artist/(\d+)", "artist"),
        (r"/browse/album/(\d+)", "album"),
        (r"/browse/playlist/([\w-]+)", "playlist"),
        (r"/track/(\d+)", "track"),
        (r"/artist/(\d+)", "artist"),
        (r"/playlist/([\w-]+)", "playlist"),
        (r"/album/\d+/track/(\d+)", "track"),
        (r"/album/(\d+)", "album"),
    ]
    
    for pattern, type_ in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), type_
    
    return None, None


async def get_stream_session(track_data: dict, user: dict):
    # ... (fungsi get_stream_session tidak berubah) ...
    media_tags = track_data['mediaMetadata']['tags']
    formats = None

    if 'tidal_api' not in user:
        raise ValueError("User dict tidak memiliki 'tidal_api' client instance.")
    
    client: TidalApi = user['tidal_api']
    
    qual, spatial, _, __ = tidal_manager.get_user_quality_settings(user["user_id"])

    if 'SONY_360RA' in media_tags and spatial == 'Sony 360RA':
        formats = '360ra'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC3 JOC':
        formats = 'ac3'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC4':
        formats = 'ac4'
    elif 'HIRES_LOSSLESS' in media_tags and qual == 'HI_RES':
        formats = 'flac_hires'

    session = {
            'flac_hires': client.mobile_hires,
            '360ra': client.mobile_hires if client.mobile_hires else client.mobile_atmos,
            'ac4': client.mobile_atmos,
            'ac3': client.tv_session,
            None: client.tv_session,
    }[formats]

    if not formats and 'DOLBY_ATMOS' in media_tags:
        if client.mobile_hires:
            session = client.mobile_hires

    quality = qual if formats != 'flac_hires' else 'HI_RES_LOSSLESS'
    return session, quality
    

def parse_mpd(xml: bytes):
    # ... (fungsi parse_mpd tidak berubah) ...
    xml = xml.decode('UTF-8')
    xml = re.sub(r'xmlns="[^"]+"', '', xml, count=1)
    root = ElementTree.fromstring(xml)
    tracks = []
    for period in root.findall('Period'):
        for adaptation_set in period.findall('AdaptationSet'):
            for rep in adaptation_set.findall('Representation'):
                content_type = adaptation_set.get('contentType')
                if content_type != 'audio':
                    raise ValueError('Only supports audio MPDs!')
                codec = rep.get('codecs').upper()
                if codec.startswith('MP4A'):
                    codec = 'AAC'
                seg_template = rep.find('SegmentTemplate')
                track_urls = [seg_template.get('initialization')]
                start_number = int(seg_template.get('startNumber') or 1)
                seg_timeline = seg_template.find('SegmentTimeline')
                if seg_timeline is not None:
                    seg_time_list = []
                    cur_time = 0
                    for s in seg_timeline.findall('S'):
                        if s.get('t'):
                            cur_time = int(s.get('t'))
                        for i in range((int(s.get('r') or 0) + 1)):
                            seg_time_list.append(cur_time)
                            cur_time += int(s.get('d'))
                    seg_num_list = list(range(start_number, len(seg_time_list) + start_number))
                    track_urls += [seg_template.get('media').replace('$Number$', str(n)) for n in seg_num_list]
                tracks.append(track_urls)
    return tracks, codec


async def merge_tracks(temp_tracks: list, output_path: str):
    # ... (fungsi merge_tracks tidak berubah) ...
    async with aiofiles.open(output_path, 'wb') as dest_file:
        for temp_location in temp_tracks:
            async with aiofiles.open(temp_location, 'rb') as segment_file:
                while True:
                    chunk = await segment_file.read(1024 * 64)
                    if not chunk:
                        break
                    await dest_file.write(chunk)
    delete_tasks = [asyncio.to_thread(os.remove, temp_location) for temp_location in temp_tracks]
    await asyncio.gather(*delete_tasks)

async def get_quality(stream_data: dict):
    # ... (fungsi get_quality tidak berubah) ...
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
    # ... (fungsi sort_album_from_artist tidak berubah) ...
    albums = []
    _, spatial, _, __ = tidal_manager.get_user_quality_settings(user["user_id"])

    for album in album_data:
        if album['audioModes'] == ['DOLBY_ATMOS'] \
            and spatial in ['ATMOS AC3 JOC', 'ATMOS AC4']: 
            albums.append(album)
        elif album['audioModes'] == ['STEREO'] \
            and spatial == 'OFF':
            albums.append(album)

    unique_albums = {}
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


# --- MODIFIKASI BESAR: ffmpeg_convert sekarang menulis SEMUA metadata ---
async def ffmpeg_convert_and_tag(input_file: str, track_meta: dict):
    """
    Mengonversi M4A (ALAC) ke FLAC dan menulis semua tag metadata
    menggunakan FFmpeg dalam satu perintah.
    """
    
    def escape_str(value):
        """Helper untuk meng-escape metadata untuk FFmpeg."""
        if value is None:
            value = ''
        if not isinstance(value, str):
            value = str(value)
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$").replace("`", "\\`")

    input_file_escaped = escape_str(input_file)
    output_file_escaped = f"{input_file_escaped}.flac"
    
    # 1. Bangun string metadata
    metadata_cmd = ""
    
    # --- PERBAIKAN: Gunakan nama tag VORBIS COMMENT (UPPERCASE) ---
    tags_to_write = {
        'TITLE': track_meta.get('title'),
        'ALBUM': track_meta.get('album'),
        'ALBUMARTIST': track_meta.get('albumartist'),
        'ARTIST': track_meta.get('artist'),
        'COPYRIGHT': track_meta.get('copyright'),
        'TRACKNUMBER': track_meta.get('tracknumber'),
        'TRACKTOTAL': track_meta.get('totaltracks'),
        'GENRE': track_meta.get('genre'),
        'DATE': track_meta.get('date'),
        'RELEASETIME': track_meta.get('release_date'), # Tag kustom
        'ISRC': track_meta.get('isrc'),
        'LYRICS': track_meta.get('lyrics'),
        'DISCNUMBER': track_meta.get('volume'), # Kunci yang benar
        'DISCTOTAL': track_meta.get('totalvolume'), # Kunci yang benar
        'COMPOSER': track_meta.get('composer'),
        'BPS': track_meta.get('bit_depth'),
        'SAMPLERATE': int(track_meta.get('sample_rate', 44.1) * 1000)
    }
    # --- AKHIR PERBAIKAN ---

    # Tambahkan tag MQA jika ada
    if track_meta.get('mqa_details'):
        mqa_file = track_meta['mqa_details']
        encoder_time = datetime.now().strftime("%b %d %Y %H:%M:%S")
        mqa_encoder_str = f'MQAEncode v1.1, 2.4.0+0 (278f5dd), E24F1DE5-32F1-4930-8197-24954EB9D6F4, {encoder_time}'
        tags_to_write['ENCODER'] = mqa_encoder_str
        tags_to_write['MQAENCODER'] = mqa_encoder_str
        tags_to_write['ORIGINALSAMPLERATE'] = str(mqa_file.original_sample_rate)

    # Buat argumen -metadata
    for key, value in tags_to_write.items():
        if value is not None and value != '':
            metadata_cmd += f' -metadata {key}="{escape_str(value)}"'

    # 2. Bangun perintah FFmpeg
    cmd = (
        f'ffmpeg -i "{input_file_escaped}" '
        f'-c:a flac -compression_level 8 ' # Konversi ke FLAC
        f'{metadata_cmd} ' # Tambahkan semua tag metadata
        f'-loglevel error -y "{output_file_escaped}"' # Output
    )
    
    logging.info(f"FFMPEG CMD: {cmd}") # Tetap log perintah ini

    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
# --- AKHIR MODIFIKASI BESAR ---
