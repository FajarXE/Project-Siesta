# [GANTI FILE: bot/helpers/napster/api.py]

import base64
import json
import requests
from bot.logger import LOGGER

class NapsterError(Exception):
    """Pengecualian kustom untuk Napster"""
    pass

class NapsterAPI:
    def __init__(self, exception, api_key, customer_secret):
        self.API_URL = 'https://api.napster.com'
        self.API_VERSION = 'v2.2'
        
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

    def _handle_response(self, response, context="API Request"):
        """Helper untuk menangani respons JSON dengan aman."""
        try:
            return response.json()
        except json.JSONDecodeError:
            LOGGER.error(f"Napster {context} Failed (Non-JSON): Status {response.status_code} | Body: {response.text[:500]}")
            raise self.exception(f"{context} gagal: Respons server tidak valid (Bukan JSON). Status: {response.status_code}")

    def login(self, username, password, current_timestamp):
        basic_token = base64.b64encode(f'{self.api_key}:{self.customer_secret}'.encode()).decode()
        data = {
            'username': username,
            'password': password,
            'grant_type': 'password'
        }

        headers = {**self.headers, 'Authorization': 'Basic ' + basic_token}
        
        # Request Login
        r = requests.post(self.API_URL + '/oauth/token', data=data, headers=headers)
        
        # Parsing JSON
        r_json = self._handle_response(r, "Login")

        # --- PERBAIKAN: Penanganan Error Server Napster yang Spesifik ---
        if r.status_code != 200: 
            error_msg = r_json.get('message', '')
            
            # Deteksi error "Cannot read property 'catalog' of undefined"
            if "catalog" in error_msg and "undefined" in error_msg:
                LOGGER.error(f"Napster Login Error (Server Side): Akun {username} mungkin salah password atau tidak punya langganan aktif.")
                raise self.exception(f"Login gagal: Kredensial salah atau akun tidak aktif (Server: {error_msg})")
            
            raise self.exception(f"Login gagal: {error_msg} (Status: {r.status_code})")

        self.access_token = r_json['access_token']
        
        # --- PERBAIKAN: Fallback jika 'catalog' tidak dikembalikan server ---
        self.catalog_region = r_json.get('catalog', 'US') 
        if not r_json.get('catalog'):
            LOGGER.warning(f"Napster: Katalog tidak ditemukan di respons login, default ke '{self.catalog_region}'.")
        
        LOGGER.info(f"Napster: Login dasar berhasil (Catalog: {self.catalog_region}), mengambil detail akun...")
        
        try:
            # Ambil detail akun untuk cek bitrate
            r2 = self._get('me/account')
            
            self.max_bitrate = r2['account']['entitlements']['maxStreamBitrate']
            self.hires_enabled = r2['account']['entitlements']['canStreamHiRes']
            self.user_id = r2['account'].get('id', 'N/A')

            LOGGER.info(f"Napster: Login penuh berhasil untuk user {self.user_id}. Max Bitrate: {self.max_bitrate}, HiRes: {self.hires_enabled}")
        except Exception as e:
            LOGGER.warning(f"Napster: Gagal mengambil detail akun tambahan, menggunakan default. Error: {e}")
            self.user_id = 'Unknown'
        
        return self.access_token, r_json['refresh_token'], r_json['expires_in'] + current_timestamp, self.catalog_region, \
            self.max_bitrate, self.hires_enabled
    
    def refresh_login(self, refresh_token, current_timestamp):
        data = {
            'client_id': self.api_key,
            'client_secret': self.customer_secret,
            'refresh_token': refresh_token,
            'response_type': 'token',
            'grant_type': 'refresh_token'
        }

        r = requests.post(self.API_URL + '/oauth/access_token', data=data, headers=self.headers)
        r_json = self._handle_response(r, "Refresh Token")

        if r.status_code != 200: 
            raise self.exception(r_json.get('message', 'Refresh token gagal'))

        self.access_token = r_json['access_token']
        return self.access_token, r_json['expires_in'] + current_timestamp

    def _get(self, url, params = {}):
        headers = {**self.headers, 'Authorization': 'Bearer ' + self.access_token}
        
        if 'catalog' not in params and self.catalog_region:
            params['catalog'] = self.catalog_region
            
        r = requests.get(f'{self.API_URL}/{self.API_VERSION}/{url}', params=params, headers=headers)
        r_json = self._handle_response(r, f"GET {url}")
        
        if r.status_code not in [200, 201, 202]: 
            raise self.exception(r_json.get('message', f'API Error {r.status_code}'))
        return r_json
    
    def search(self, query_type, query, limit = 10, offset = 0):
        params = {
            'query': query,
            'type': query_type,
            'per_type_limit': limit,
            'rights': '2',
            'offset': offset
        }
        return self._get('search', params)['search']['data'][query_type+'s']
    
    def get_items_list(self, item_type, item_ids, item_sub='', item_string='', limit=50):
        if item_ids:
            if isinstance(item_ids, list): item_ids = ','.join(item_ids)
            r = self._get(f'{item_type}/{item_ids}' + (f'/{item_sub}' if item_sub else ''), {'limit': limit})
            
            target_key = item_string if item_string else item_type
            if target_key not in r:
                 return []

            results = r[target_key]
            
            requested, total = r['meta']['returnedCount'], r['meta']['totalCount']
            if not total: total = 0
            
            while requested < total:
                r = self._get(f'{item_type}/{item_ids}' + (f'/{item_sub}' if item_sub else ''), {'limit': limit, 'offset': requested})
                if target_key in r:
                    results += r[target_key]
                    requested += r['meta']['returnedCount']
                else:
                    break

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
            'protocol': '', 
            'track': track_id
        }
        data = self._get('streams', params)
        if not data.get('streams'):
            raise self.exception(f"Tidak ada stream yang ditemukan untuk track {track_id} (Bitrate: {bitrate}, Codec: {codec})")
        return data['streams'][0]['url']
