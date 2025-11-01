# [GANTI FILE: bot/helpers/deezer/metadata.py]

import copy
from datetime import datetime

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .dzapi import deezerapi
from bot.logger import LOGGER


async def process_track_metadata(track_id, r_id, cover=None, 
    thumbnail=None, total_tracks=None, album_genre=None, total_disks=None): 
    metadata = copy.deepcopy(base_meta)

    # --- MODIFIKASI: Ganti ke get_track_data (song.getData) untuk data LENGKAP ---
    # get_track (deezer.pageTrack) tidak mengembalikan genre/contributors
    raw_meta = await deezerapi.get_track_data(track_id)
    # 'get_track_data' tidak memiliki 'DATA' wrapper, jadi kita langsung gunakan raw_meta
    t_meta = raw_meta.get('FALLBACK', raw_meta)
    # --- BATAS MODIFIKASI ---
    
    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = track_id
    metadata['copyright'] = t_meta.get('COPYRIGHT', '')
    metadata['albumartist'] = t_meta['ART_NAME']
    metadata['artist'] = get_artists_name(t_meta)
    metadata['album'] = t_meta['ALB_TITLE']
    metadata['isrc'] = t_meta['ISRC']

    metadata['title'] = t_meta['SNG_TITLE']
    if t_meta.get('VERSION'):
        metadata['title'] += f' ({t_meta["VERSION"]})'

    metadata['title'] = metadata['title'].replace('/', ' ')

    metadata['duration'] = t_meta['DURATION']
    
    try:
        explicit_status = t_meta.get('EXPLICIT_TRACK_CONTENT', {}).get('EXPLICIT_LYRICS_STATUS', 0)
        metadata['explicit'] = True if explicit_status == 1 else False
    except Exception:
        metadata['explicit'] = False 
    
    metadata['tracknumber'] = t_meta['TRACK_NUMBER']

    if total_tracks:
        metadata['totaltracks'] = total_tracks

    metadata['date'] = t_meta.get('PHYSICAL_RELEASE_DATE', '')

    metadata['provider'] = 'Deezer'
    metadata['type'] = 'track'
    
    if album_genre:
        metadata['genre'] = album_genre
    elif t_meta.get('GENRE_NAME'):
         metadata['genre'] = t_meta['GENRE_NAME']
         
    metadata['volume'] = str(t_meta.get('DISK_NUMBER', '1'))
    
    if total_disks:
        metadata['totalvolume'] = str(total_disks)
    
    if t_meta.get('CONTRIBUTORS'):
        composers = []
        for contributor in t_meta['CONTRIBUTORS']:
            role_id = str(contributor.get('ROLE_ID'))
            if role_id in ['1', '4', '5']: # Composer (1), Writer (4), Lyricist (5)
                composers.append(contributor.get('ART_NAME'))
        if composers:
            metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))

    metadata['cover'] = cover if cover else await get_cover(t_meta['ALB_PICTURE'], metadata)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(t_meta['ALB_PICTURE'], metadata, True)

    metadata['token'] = t_meta['TRACK_TOKEN']
    metadata['token_expiry'] = t_meta['TRACK_TOKEN_EXPIRE']

    metadata['quality'] = await get_quality(t_meta)

    return metadata
            

async def process_album_metadata(album_id:int, a_meta:dict, t_meta:list, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = album_id

    metadata['albumartist'] = a_meta['ART_NAME']
    metadata['upc'] = a_meta['UPC']
    metadata['title'] = a_meta['ALB_TITLE']
    if a_meta.get('VERSION'):
        metadata['title'] += f' ({a_meta["VERSION"]})'
    metadata['album'] = a_meta['ALB_TITLE']
    metadata['artist'] = get_artists_name(a_meta)
    metadata['date'] = a_meta['DIGITAL_RELEASE_DATE']
    metadata['totaltracks'] = a_meta['NUMBER_TRACK'] 
    metadata['duration'] = a_meta['DURATION']
    metadata['copyright'] = a_meta['COPYRIGHT']
    metadata['explicit'] = a_meta.get('explicit_lyrics', False)
    
    album_genre_name = ''
    if a_meta.get('genres') and a_meta.get('genres').get('data'):
        if a_meta['genres']['data']:
            album_genre_name = a_meta['genres']['data'][0].get('NAME', '')
            metadata['genre'] = album_genre_name
    
    metadata['totalvolume'] = str(a_meta.get('DISK_COUNT', '1'))
    
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'

    metadata['cover'] = await get_cover(a_meta['ALB_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(a_meta['ALB_PICTURE'], metadata, True)
        
    metadata['tracks'] = []
    for track in t_meta['data']:
        track_meta = await process_track_metadata(
            track['SNG_ID'], 
            r_id,
            metadata['cover'], 
            metadata['thumbnail'],
            metadata['totaltracks'],
            album_genre_name, 
            metadata['totalvolume']
        )
        metadata['tracks'].append(track_meta)

    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
    else:
        metadata['quality'] = "N/A"
    
    return metadata



async def process_playlist_meta(raw_meta, r_id):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['title'] = raw_meta['DATA']['TITLE']
    metadata['duration'] = raw_meta['DATA']['DURATION']
    metadata['totaltracks'] = raw_meta['DATA']['NB_SONG'] 
    metadata['itemid'] = raw_meta['DATA']['PLAYLIST_ID']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Deezer'
    metadata['cover'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata, True)
    
    for track in raw_meta['SONGS']['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], 
                r_id,
                total_tracks=metadata['totaltracks'] 
            )
        except:
            continue
        metadata['tracks'].append(track_meta)

    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
    else:
        metadata['quality'] = "N/A"

    return metadata

def get_artists_name(meta:dict):
    artists = []
    if meta.get('ARTISTS'):
        for a in meta['ARTISTS']:
            artists.append(a['ART_NAME'])
    return ', '.join([str(artist) for artist in artists])


async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (
            f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/3000x0-none-100-0-0.png'
            if not thumbnail
            else f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/80x0-none-100-0-0.png'
        )
    return await create_cover_file(url, meta, thumbnail)


async def get_quality(meta:dict):
    format = 'FLAC'
    premium_formats = ['FLAC', 'MP3_320']
    countries = meta.get('AVAILABLE_COUNTRIES', {}).get('STREAM_ADS')
    
    if not countries:
        raise Exception("Deezer : Track not available")
    elif deezerapi.country not in countries:
        raise Exception("Deezer : Track not available in your country")
    else:
        formats_to_check = premium_formats
        while len(formats_to_check) != 0:
            if formats_to_check[0] != format:
                formats_to_check.pop(0)
            else:
                break

        temp_f = None
        for f in formats_to_check:
            if f'FILESIZE_{f}' in meta and meta[f'FILESIZE_{f}'] != '0':
                temp_f = f
                break
        if temp_f is None:
            temp_f = 'MP3_128'
        format = temp_f

        if format not in deezerapi.available_formats:
            raise Exception("Deezer : Format not available by your subscription")

    return format
