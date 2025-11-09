# [BUAT FILE BARU: bot/helpers/napster/api.py]

import base64
import json
import requests # Modifikasi: Impor requests standar
from bot.logger import LOGGER # Modifikasi: Impor logger bot Anda

class NapsterError(Exception):
    """Pengecualian kustom untuk Napster"""
    pass

class NapsterAPI:
    def __init__(self, exception, api_key, customer_secret):
        self.API_URL = 'https://api.napster.com'
        self.API_VERSION = 'v2.2'
        # Modifikasi: Ganti create_requests_session dengan requests.Session()
        self.s = requests.Session() 
        self.exception = exception

        self.api_key = api_key
        self.customer_secret = customer_secret
        self.headers = {
            'apikey': api_key,
            'Connection': 'Keep-Alive',
            'User-Agent': 'okhttp/4.9.1'
        }

        self.access_token = None
        self.catalog_region = None
        self.max_bitrate = 320 # Default
        self.hires_enabled = False # Default

    def login(self, username, password, current_timestamp):
        basic_token = base64.b64encode(f'{self.api_key}:{self.customer_secret}'.encode()).decode()
        data = {
            'username': username,
            'password': password,
            'grant_type': 'password'
        }

        headers = {**self.headers, 'Authorization': 'Basic ' + basic_token}
        r = self.s.post(self.API_URL + '/oauth/token', data, headers=headers)
        if r.status_code != 200: 
            raise self.exception(r.json().get('message', 'Login gagal'))

        r = r.json()
        self.access_token = r['access_token']
        self.catalog_region = r['catalog']
        
        LOGGER.info(f"Napster: Login dasar berhasil, mengambil detail akun...")
        r2 = self._get('me/account')
        
        # Simpan detail penting ke dalam objek klien
        self.max_bitrate = r2['account']['entitlements']['maxStreamBitrate']
        self.hires_enabled = r2['account']['entitlements']['canStreamHiRes']
        self.user_id = r2['account'].get('id', 'N/A')

        LOGGER.info(f"Napster: Login penuh berhasil untuk user {self.user_id}. Max Bitrate: {self.max_bitrate}, HiRes: {self.hires_enabled}")
        
        # Kembalikan token untuk disimpan (meskipun kita juga menyimpannya di sini)
        return r['access_token'], r['refresh_token'], r['expires_in'] + current_timestamp, r['catalog'], \
            self.max_bitrate, self.hires_enabled
    
    def refresh_login(self, refresh_token, current_timestamp):
        data = {
            'client_id': self.api_key,
            'client_secret': self.customer_secret,
            'refresh_token': refresh_token,
            'response_type': 'token',
            'grant_type': 'refresh_token'
        }

        r = self.s.post(self.API_URL + '/oauth/access_token', data, headers=self.headers)
        if r.status_code != 200: 
            raise self.exception(r.json().get('message', 'Refresh token gagal'))

        r = r.json()
        self.access_token = r['access_token']
        return r['access_token'], r['expires_in'] + current_timestamp

    def _get(self, url, params = {}):
        headers = {**self.headers, 'Authorization': 'Bearer ' + self.access_token}
        
        # Tambahkan katalog default jika tidak ada
        if 'catalog' not in params:
            params['catalog'] = self.catalog_region
            
        r = self.s.get(f'{self.API_URL}/{self.API_VERSION}/{url}', params=params, headers=headers)
        if r.status_code not in [200, 201, 202]: 
            raise self.exception(r.json().get('message', f'API Error {r.status_code}'))
        return r.json()
    
    def search(self, query_type, query, limit = 10, offset = 0):
        params = {
            'query': query,
            'type': query_type,
            'per_type_limit': limit,
            'rights': '2', # '2' mungkin berarti streamable?
            'offset': offset
        }
        return self._get('search', params)['search']['data'][query_type+'s']
    
    def get_items_list(self, item_type, item_ids, item_sub='', item_string='', limit=50):
        if item_ids:
            if isinstance(item_ids, list): item_ids = ','.join(item_ids)
            r = self._get(f'{item_type}/{item_ids}' + (f'/{item_sub}' if item_sub else ''), {'limit': limit})
            results = r[item_string if item_string else item_type]
            
            requested, total = r['meta']['returnedCount'], r['meta']['totalCount']
            if not total: total = 0
            while requested < total:
                r = self._get(f'{item_type}/{item_ids}' + (f'/{item_sub}' if item_sub else ''), {'limit': limit, 'offset': requested})
                results += r[item_string if item_string else item_type] if item_ids else []
                requested += r['meta']['returnedCount']

            return results
        else:
            return []

    def get_items_dict(self, item_type, item_ids, item_sub='', item_string='', limit=50):
        return {i['id']: i for i in self.get_items_list(item_type, item_ids, item_sub, item_string, limit)}
    
    def get_string_from_items_list(self, item_type, item_ids, string_key, item_sub='', item_string='', limit=50):
        return {i['id']: i[string_key] for i in self.get_items_list(item_type, item_ids, item_sub, item_string, limit)}
    
    def get_stream_url(self, bitrate, codec, track_id):
        params = {
            'bitrate': bitrate,
            'format': codec,
            'protocol': '', # Kosong mungkin default ke HTTP
            'track': track_id
        }
        # Logika dari interface.py
        data = self._get('streams', params)
        if not data.get('streams'):
            raise self.exception(f"Tidak ada stream yang ditemukan untuk track {track_id} (Bitrate: {bitrate}, Codec: {codec})")
        return data['streams'][0]['url']
