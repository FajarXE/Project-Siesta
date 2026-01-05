import aiohttp
from .api import BandcampAPI

class BandcampManager:
    def __init__(self):
        self.session = None
        self.api = BandcampAPI() # Inisialisasi API class

    async def initialize_clients(self):
        self.session = aiohttp.ClientSession()

    async def shutdown(self):
        if self.session:
            await self.session.close()

    def get_client(self):
        return self.api

bandcamp_manager = BandcampManager()
