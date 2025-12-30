import aiohttp
from .api import JioSaavnAPI

class JioSaavnManager:
    def __init__(self):
        self.api = JioSaavnAPI()
        self.session = None

    async def initialize_clients(self):
        # JioSaavn adalah public API, tidak butuh login user
        self.session = aiohttp.ClientSession()

    async def shutdown(self):
        if self.session:
            await self.session.close()

    def get_client(self):
        return self.api

jiosaavn_manager = JioSaavnManager()
