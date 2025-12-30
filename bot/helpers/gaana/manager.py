import aiohttp
from .api import GaanaAPI

class GaanaManager:
    def __init__(self):
        self.api = GaanaAPI()
        self.session = None

    async def initialize_clients(self):
        self.session = aiohttp.ClientSession()

    async def shutdown(self):
        if self.session:
            await self.session.close()

    def get_client(self):
        return self.api

gaana_manager = GaanaManager()
