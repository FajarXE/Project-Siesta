# From vitiko98/qobuz-dl
import re
import copy
import bot.helpers.translations as lang
import logging

from ..message import send_message, edit_message
from ..utils import format_string
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file

from bot.settings import bot_set
from config import Config

# --- MODIFIKASI: Impor QobuzContentUnavailableError dari handler ---
try:
    from .handler import QobuzContentUnavailableError
except ImportError:
    class QobuzContentUnavailableError(Exception):
        pass
# --- BATAS MODIFIKASI ---


async def get_track_metadata(item_id, r_id, q_meta=None, user: dict=None):
    if user is None:
        logging.error("User dict None in get_track_metadata! Multi-login will fail.")
        return None, "Error: User data tidak ditemukan."
    
    client = user['qobuz_api'] 

    if q_meta is None:
        raw_meta = await client.get_track_url(item_id, user)
        if "sample" not in raw_meta and raw_meta.get('sampling_rate'):
            q_meta = await client.get_track_meta(item_id)
            if not q_meta.get('streamable'):
                return None, "UNAVAILABLE" 
        else:
            return None, "UNAVAILABLE"
    
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = item_id
    metadata['copyright'] = q_meta['copyright']
    metadata['albumartist'] = q_meta['album']['artist']['name']
    metadata['artist'] = await get_artists_name(q_meta['album'])
    metadata['upc'] = q_meta['album']['upc']
    metadata['album'] = q_meta['album']['title']
    metadata['isrc'] = q_meta['isrc']

    metadata['title'] = q_meta['title']
    if q_meta['version']:
        metadata['title'] += f' ({q_meta["version"]})'

    metadata['duration'] = q_meta['duration']
    metadata['explicit'] = q_meta['parental_warning']
    metadata['tracknumber'] = q_meta['track_number']
    metadata['date'] = q_meta['release_date_original']
    metadata['totaltracks'] = q_meta['album']['tracks_count']
    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'track'

    metadata['cover'] = await create_cover_file(q_meta['album']['image']['large'], metadata)
    metadata['thumbnail'] = await create_cover_file(q_meta['album']['image']['thumbnail'], metadata, True)

    return metadata, None  
        
async def get_album_metadata(item_id, r_id, user: dict):
    client = user['qobuz_api'] 
    q_meta = await client.get_album_meta(item_id)
    
    if not q_meta.get('streamable'):
        return None, "UNAVAILABLE"
    
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['itemid'] = item_id
    metadata['albumartist'] = q_meta['artist']['name']
    metadata['upc'] = q_meta['upc']
    metadata['title'] = q_meta['title']
    metadata['album'] = q_meta['title']
    metadata['artist'] = q_meta['artist']['name']
    metadata['date'] = q_meta['release_date_original']
    metadata['totaltracks'] = q_meta['tracks_count']
    metadata['duration'] = q_meta['duration']
    metadata['copyright'] = q_meta['copyright']
    metadata['genre'] = q_meta['genre']['name']
    metadata['explicit'] = q_meta['parental_warning']
    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'album'

    metadata['cover'] = await create_cover_file(q_meta['image']['large'], metadata)
    metadata['thumbnail'] = await create_cover_file(q_meta['image']['thumbnail'], metadata, True)

    metadata['tracks'] = await get_track_meta_from_alb(q_meta, metadata) 

    return metadata, None

async def get_track_meta_from_alb(q_meta:dict, alb_meta):
    tracks = []
    for track in q_meta['tracks']['items']:
        metadata = copy.deepcopy(alb_meta)
        metadata['itemid'] = track['id']

        metadata['title'] = track['title']
        if track['version']:
            metadata['title'] += f' ({track["version"]})'

        metadata['duration'] = track['duration']
        metadata['isrc'] = track['isrc']
        metadata['tracknumber'] = track['track_number']
        metadata['tracks'] = ''
        metadata['type'] = 'track'
        tracks.append(metadata)
    return tracks


async def get_playlist_meta(raw_meta, tracks, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['title'] = raw_meta['name']
    metadata['duration'] = raw_meta['duration']
    metadata['totaltracks'] = raw_meta['tracks_count']
    metadata['itemid'] = raw_meta['id']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Qobuz'
    metadata['cover'] = './project-siesta.png'
    metadata['thumbnail'] = './project-siesta.png'
    
    for track in tracks:
        track_meta, err = await get_track_metadata(track['id'], r_id, track, user=user)
        if err:
            if err == "UNAVAILABLE":
                raise QobuzContentUnavailableError(f"Track {track['id']} di playlist tidak tersedia.")
        metadata['tracks'].append(track_meta)
    return metadata

async def get_artist_meta(artist_raw):
    metadata = copy.deepcopy(base_meta)
    metadata['title'] = artist_raw['name']
    metadata['type'] = 'artist'
    metadata['provider'] = 'Qobuz'
    return metadata

async def get_artists_name(meta):
    artists = []
    try:
        for a in meta['artists']:
            artists.append(a['name'])
    except:
        artists.append(meta['artist']['name'])
    return ', '.join([str(artist) for artist in artists])


async def check_type(url, user: dict):
    client = user['qobuz_api'] 

    possibles = {
            "playlist": {
                "func": "get_plist_meta", 
                "iterable_key": "tracks",
                "multi_type": "tracks" 
            },
            "artist": {
                "func": "get_artist_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "interpreter": {
                "func": "get_artist_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "label": {
                "func": "get_label_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "album": {"album": True, "func": None, "iterable_key": None},
            "track": {"album": False, "func": None, "iterable_key": None},
        }
    try:
        url_type, item_id = await get_url_info(url)
        type_dict = possibles[url_type]
    except (KeyError, IndexError):
        raise Exception(f"URL tidak dapat dikenali: {url}")

    content = None
    items = None
    
    if type_dict["func"]:
        method_to_call = getattr(client, type_dict["func"])
        
        content = []
        
        # --- PERBAIKAN: Perbaiki logika pengumpulan hasil dari generator ---
        if type_dict["multi_type"]:
            
            if url_type == "playlist":
                epoint = "playlist/get"
                key = "tracks_count"
            elif url_type in ["artist", "label", "interpreter"]:
                epoint = f"{url_type}/get"
                key = "albums_count"
            else:
                raise Exception("Tipe multi-meta tidak terdefinisi.")

            res_iterator = client.multi_meta(epoint, key, item_id, type_dict["multi_type"])
            
            async for data in res_iterator:
                content.append(data)
                
            if not content:
                # Jika content kosong, multi_meta gagal, lempar exception untuk fallback
                raise QobuzContentUnavailableError(f"API Qobuz gagal mengembalikan data untuk {url_type}/{item_id}. Coba akun lain.")


        if content:
            smart_discography = True
            if smart_discography and url_type == "artist":
                items = smart_discography_filter(
                    content,
                    save_space=True,
                    skip_extras=True,
                )
            else:
                if url_type == 'playlist':
                    if 'items' in content[0]:
                        items = content[0]['items']
                    else:
                        raise QobuzContentUnavailableError(f"Playlist ID:{item_id} kosong atau tidak memiliki track.")
                
                elif len(content) > 0 and type_dict["iterable_key"] in content[0]:
                    items = [item[type_dict["iterable_key"]]["items"] for item in content][0]
                else:
                    raise Exception("Gagal memparsing struktur respons Qobuz.")
        # --- BATAS PERBAIKAN ---
            
        return items, item_id, type_dict, content
    else:
        return None, item_id, type_dict, content


async def get_url_info(url):
    r = re.search(
        r"(?:https:\/\/(?:w{3}|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})"
        r"?\/(album|artist|track|playlist|label|interpreter)(?:\/[-\w\d]+)?\/([\w\d]+)",
        url,
    )
    return r.groups()


def smart_discography_filter(
    contents: list, save_space: bool = False, skip_extras: bool = False
) -> list:

    TYPE_REGEXES = {
        "remaster": r"(?i)(re)?master(ed)?",
        "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)",
    }

    def is_type(album_t: str, album: dict) -> bool:
        version = album.get("version", "")
        title = album.get("title", "")
        regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None

    def essence(album: dict) -> str:
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album)
        if not r:
            return album.lower()
        return r.group(1).strip().lower()

    requested_artist = contents[0]["name"]
    items = [item["albums"]["items"] for item in contents][0]

    title_grouped = dict()
    for item in items:
        title_ = essence(item["title"])
        if title_ not in title_grouped:
            title_grouped[title_] = []
        title_grouped[title_].append(item)

    items = []
    for albums in title_grouped.values():
        best_bit_depth = max(a["maximum_bit_depth"] for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a["maximum_sampling_rate"]
            for a in albums
            if a["maximum_bit_depth"] == best_bit_depth
        )
        remaster_exists = any(is_type("remaster", a) for a in albums)

        def is_valid(album: dict) -> bool:
            return (
                album["maximum_bit_depth"] == best_bit_depth
                and album["maximum_sampling_rate"] == best_sampling_rate
                and album["artist"]["name"] == requested_artist
                and not (
                    (remaster_exists and not is_type("remaster", album))
                    or (skip_extras and is_type("extra", album))
                )
            )

        filtered = tuple(filter(is_valid, albums))
        if len(filtered) >= 1:
            items.append(filtered[0])

    return items

    
async def get_quality(meta: dict, user: dict):
    client = user['qobuz_api'] 
    user_dict = client.user_data.get(user.get("user_id", 0), {})
    quality = user_dict.get("qobuz_qual", client.quality)
    if quality == 5:
        return 'mp3', '320K'
    else:
        return 'flac', f'{meta["bit_depth"]}B - {meta["sampling_rate"]}k'
