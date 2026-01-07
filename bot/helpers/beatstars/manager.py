# [FILE BARU: bot/helpers/beatstars/manager.py]

from bot.logger import LOGGER

class BeatStarsManager:
    def __init__(self):
        self.clients = {} # Tidak butuh login, tapi disiapkan untuk struktur
        self.config = {}

    async def initialize_clients(self):
        # BeatStars menggunakan Public API (Algolia), tidak perlu login user.
        LOGGER.info("BeatStars: Inisialisasi berhasil (Mode Publik/Algolia).")
        return

beatstars_manager = BeatStarsManager()
