# [GANTI FILE: bot/helpers/lyrics/apis.py]

import aiohttp
import asyncio
import time
import uuid
import hmac
import base64
import logging
import json
from urllib.parse import quote, urlencode
from datetime import datetime

LOGGER = logging.getLogger(__name__)

class MusixmatchAPI:
    def __init__(self):
        self.API_URL = 'https://apic-desktop.musixmatch.com/ws/1.1/'
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Musixmatch/0.19.4 Chrome/58.0.3029.110 Electron/1.7.6 Safari/537.36',
            'Cookie': 'AWSELB=unknown; AWSELBCORS=unknown' 
        }
        self.token = None

    def sign_request(self, method, params, timestamp):
        # Pastikan urutan parameter konsisten jika diperlukan, tapi untuk HMAC ini biasanya cukup
        to_hash = self.API_URL + method + '?' + urlencode(params)
        key = ("IEJ5E8XFaH" "QvIQNfs7IC").encode()
        signature = hmac.digest(key, (to_hash + timestamp).encode(), digest='SHA1')
        return base64.urlsafe_b64encode(signature).decode()

    async def get_token(self, session):
        currenttime = datetime.now()
        timestamp = currenttime.strftime('%Y-%m-%dT%H:%M:%SZ')
        signature_timestamp = currenttime.strftime('%Y%m%d')
        method = 'token.get'
        params = {
            'format': 'json',
            'guid': str(uuid.uuid4()),
            'timestamp': timestamp,
            'build_number': '2017091202',
            'lang': 'en-GB',
            'app_id': 'web-desktop-app-v1.0'
        }
        params['signature'] = self.sign_request(method, params, signature_timestamp)
        params['signature_protocol'] = 'sha1'

        async with session.get(self.API_URL + method, params=params, headers=self.headers) as r:
            # PERBAIKAN: Tambahkan content_type=None agar tidak error saat menerima text/plain
            data = await r.json(content_type=None) 
            if data['message']['header']['status_code'] == 200:
                self.token = data['message']['body']['user_token']
                return self.token
        return None

    async def get_lyrics(self, title, artist, album, duration=None):
        async with aiohttp.ClientSession() as session:
            if not self.token:
                await self.get_token(session)

            # 1. Search Track
            method = 'track.search'
            params = {
                'format': 'json',
                'q_track': title,
                'q_artist': artist,
                'quorum_factor': 1,
                'usertoken': self.token,
                'app_id': 'web-desktop-app-v1.0'
            }
            
            track_id = None
            async with session.get(self.API_URL + method, params=params, headers=self.headers) as r:
                # PERBAIKAN: Tambahkan content_type=None
                data = await r.json(content_type=None)
                try:
                    track_list = data['message']['body']['track_list']
                    if track_list:
                        track_id = track_list[0]['track']['track_id']
                except:
                    pass

            if not track_id:
                return None, None

            # 2. Get Lyrics (Plain & Synced)
            plain = None
            synced = None
            
            # Fetch Macro (All in one)
            method = 'macro.subtitles.get'
            params = {
                'format': 'json',
                'q_track': title,
                'q_artist': artist,
                'usertoken': self.token,
                'app_id': 'web-desktop-app-v1.0',
                'namespace': 'lyrics_richsynched',
                'optional_calls': 'track.richsync,track.lyrics.get'
            }
            
            async with session.get(self.API_URL + method, params=params, headers=self.headers) as r:
                # PERBAIKAN: Tambahkan content_type=None
                data = await r.json(content_type=None)
                body = data['message']['body']['macro_calls']
                
                # Extract Plain
                if body.get('track.lyrics.get', {}).get('message', {}).get('header', {}).get('status_code') == 200:
                    plain = body['track.lyrics.get']['message']['body']['lyrics']['lyrics_body']

                # Extract Synced (Richsync) - Ini format JSON khusus Musixmatch
                if body.get('track.richsync.get', {}).get('message', {}).get('header', {}).get('status_code') == 200:
                    richsync = body['track.richsync.get']['message']['body']['richsync']
                    if richsync:
                         # Konversi Richsync ke LRC sederhana (Sangat basic)
                         # Richsync adalah daftar karakter dengan offset waktu.
                         # Kita coba ambil teks utuhnya saja jika pengguna meminta synced, 
                         # atau biarkan None karena konversinya rumit.
                         # Untuk amannya, kita kembalikan JSON string jika Anda ingin memprosesnya nanti,
                         # atau biarkan None. Di sini saya biarkan None untuk stabilitas kecuali Anda punya parser.
                         synced = None 
            
            return plain, synced


class LRCLibAPI:
    def __init__(self):
        self.base_url = 'https://lrclib.net/api'
        self.headers = {
            'User-Agent': 'BotMusic/1.0'
        }

    async def get_lyrics(self, title, artist, album, duration):
        async with aiohttp.ClientSession() as session:
            params = {
                'track_name': title,
                'artist_name': artist,
                'album_name': album,
                'duration': duration
            }
            
            # Try Cached
            async with session.get(f'{self.base_url}/get', params=params, headers=self.headers) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    return data.get('plainLyrics'), data.get('syncedLyrics')
            
            # Try Search if Get fails
            params_search = {'q': f"{title} {artist}"}
            async with session.get(f'{self.base_url}/search', params=params_search, headers=self.headers) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if data and isinstance(data, list):
                        # Ambil hasil pertama yang paling relevan
                        return data[0].get('plainLyrics'), data[0].get('syncedLyrics')
            
            return None, None
