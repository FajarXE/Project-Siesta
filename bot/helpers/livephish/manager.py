import logging
from bot.helpers.livephish.livephish_api import LivePhishApi
from config import Config

class LivePhishManager:
    def __init__(self):
        self.clients = []
        self.quality = "FLAC" # Default FLAC

    async def initialize_clients(self):
        if not Config.LIVEPHISH_ACCOUNTS:
            return
        
        for creds in Config.LIVEPHISH_ACCOUNTS:
            client = LivePhishApi()
            try:
                await client.login(creds['email'], creds['password'])
                self.clients.append(client)
                logging.info(f"LivePhish: Akun {creds['email']} berhasil login.")
            except Exception as e:
                logging.error(f"LivePhish: Gagal login akun {creds['email']} -> {e}")
                await client.close()

    def get_client(self):
        if self.clients:
            return self.clients[0]
        return None

    async def setup_quality(self, user_id, quality):
        # Kualitas: FLAC, ALAC, AAC
        self.quality = quality

    async def shutdown(self):
        for c in self.clients:
            await c.close()

livephish_manager = LivePhishManager()
