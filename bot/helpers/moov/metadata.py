import copy
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import moov_manager

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # [span_10](start_span)Mapping field dari response API[span_10](end_span)
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')
    
    # Artist
    artists = track_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    
    # Album & Copyright
    metadata['album'] = track_data.get('albumTitle')
    
    raw_copyright = track_data.get('cnote')
    metadata['copyright'] = str(raw_copyright) if raw_copyright else ""

    metadata['label'] = track_data.get('albumLabel')
    
    # Track Number
    # Note: Moov tidak selalu return track number eksplisit di list produk, 
    # seringkali urutan list adalah nomor track. Kita handle di handler.py jika perlu.
    # Namun jika ada field 'discNo' atau 'trackNo', pakai itu.
    metadata['tracknumber'] = str(track_data.get('trackNo', 1))
    
    # Provider
    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    # Cover Art
    if cover:
        metadata['cover'] = cover
    else:
        # [span_11](start_span)Ambil gambar resolusi tertinggi dari list images[span_11](end_span)
        images = track_data.get('images', [])
        if images:
            # Biasanya gambar terakhir adalah yang terbesar atau cari yang 'path' nya valid
            cover_url = images[0].get('path') 
            metadata['cover'] = await create_cover_file(cover_url, metadata)

    # Quality Selection
    # [span_12](start_span)Moov qualities: 'HR' (24bit), 'LL' (16bit)[span_12](end_span)
    avail_qualities = track_data.get('qualities', []) # list seperti ['HR', 'LL', 'HD']
    user_pref = moov_manager.get_user_quality(user['user_id']) 
    
    target_quality = 'LL' # Default 16bit FLAC
    
    if user_pref == "FLAC": # User wants Max (24bit if avail)
        if 'HR' in avail_qualities:
            target_quality = 'HR'
            metadata['quality'] = 'FLAC 24bit'
        elif 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
    else: # Fallback / MP3 preference -> Pakai LL (karena Moov focus FLAC) atau HD jika ada
        if 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
            
    metadata['extension'] = 'flac'
    metadata['moov_quality_code'] = target_quality
    
    return metadata

async def process_album_metadata(album_data: dict, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # [span_13](start_span)Album Info[span_13](end_span)
    # Moov return 'engTitle', 'chiTitle' list. Index 0 = Album Name.
    meta_lang_key = 'engTitle' # Default English
    
    titles = album_data.get(meta_lang_key, [])
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    # Artist
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    
    # Date (Year)
    if len(titles) > 2:
        metadata['date'] = titles[2].split('-')[0] # Format YYYY-MM-DD
        
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') # atau ID dari URL
    
    # Cover
    images = album_data.get('images', [])
    if images:
        metadata['cover'] = await create_cover_file(images[0].get('path'), metadata)
        
    # Tracks
    metadata['tracks'] = []
    # Tracks ada di modules -> products
    modules = album_data.get('modules', [])
    if modules:
        products = modules[0].get('products', [])
        metadata['totaltracks'] = len(products)
        
        for idx, track_raw in enumerate(products, 1):
            track_raw['trackNo'] = idx # Inject nomor urut
            t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'])
            metadata['tracks'].append(t_meta)
            
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata
