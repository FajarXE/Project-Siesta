import json
import os
import logging
from urllib.parse import urlparse, parse_qs
from .spotify_api import SpotifyAPI, StoredToken
from config import Config

LOGGER = logging.getLogger("SpotifyAuth")

class HeadlessSpotifyAuth:
    def __init__(self):
        # Konfigurasi dasar
        self.config = {
            "client_id": Config.SPOTIFY_CLIENT_ID,
            "client_secret": Config.SPOTIFY_CLIENT_SECRET,
            "username": "RenderBot"
        }
        # Inisialisasi API sementara untuk Auth
        self.api = SpotifyAPI(config=self.config)
        self.oauth = self.api.oauth_handler
        
        # Cache untuk menyimpan verifier code sementara
        self.verifier_cache = None 

    def get_login_url(self):
        """Membuat URL Login untuk dikirim ke User"""
        auth_url = self.oauth.get_authorization_url()
        # Simpan code_verifier di memory karena OAuth class akan meresetnya jika init ulang
        self.verifier_cache = self.oauth.code_verifier 
        return auth_url

    def process_callback_url(self, url_from_user):
        """Memproses URL Redirect yang dikirim user"""
        try:
            parsed = urlparse(url_from_user)
            query_params = parse_qs(parsed.query)
            
            if 'code' not in query_params:
                if 'error' in query_params:
                    return False, f"Error dari Spotify: {query_params['error'][0]}"
                return False, "URL tidak valid (tidak mengandung 'code')."

            code = query_params['code'][0]
            
            # Restore verifier code
            if self.verifier_cache:
                self.oauth.code_verifier = self.verifier_cache
            
            # Tukar Code dengan Token
            token_data = self.oauth.exchange_code_for_token(code)
            
            if token_data:
                token_obj = StoredToken(token_data)
                
                # Buat Dictionary lengkap untuk disimpan
                full_token_data = token_obj.to_dict()
                full_token_data['client_id'] = self.oauth.client_id
                full_token_data['spotify_username'] = "SpotifyUser" # Placeholder
                
                # Ubah ke JSON String
                json_str = json.dumps(full_token_data)
                return True, json_str
            else:
                return False, "Gagal menukar kode dengan token. Cek log/console."
                
        except Exception as e:
            return False, f"Exception: {str(e)}"
