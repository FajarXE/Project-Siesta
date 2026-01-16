import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...logger import LOGGER

class KhinsiderManager:
    def __init__(self):
        self.session = None
        self.quality = 'flac' # Default preference
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }

    async def initialize_clients(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        LOGGER.info("KhinsiderManager: Session initialized.")

    async def shutdown(self):
        if self.session:
            await self.session.close()

    async def setup_quality(self, user_id, quality):
        # Hanya flac atau mp3
        self.quality = quality

    async def get_album(self, url):
        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch album page: {resp.status}")
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        
        # Metadata
        title = soup.select_one("#pageContent h2")
        title = title.get_text(strip=True) if title else "Unknown Album"
        
        # Images
        images = []
        for img in soup.select("div.albumImage a"):
            href = img.get('href')
            if href:
                images.append(href)
        cover_url = images[0] if images else None

        # Tracks
        tracks = []
        table = soup.find("table", id="songlist")
        if table:
            rows = table.find_all("tr")[1:]
            for row in rows:
                if row.get("id") == "songlist_footer":
                    continue
                
                cells = row.find_all("td")
                if len(cells) < 2: 
                    continue
                
                link = row.find("a", href=True)
                if not link:
                    continue
                
                track_url = urljoin(url, link['href'])
                track_name = link.get_text(strip=True)
                
                track_num = None
                if cells[1].get_text(strip=True).isdigit():
                     track_num = cells[1].get_text(strip=True)
                
                tracks.append({
                    'title': track_name,
                    'url': track_url,
                    'track_number': track_num or str(len(tracks) + 1)
                })

        return {
            'title': title,
            'cover': cover_url,
            'tracks': tracks,
            'images': images,
            'provider': 'Khinsider'
        }

    async def get_track_download_url(self, track_url, preferred_formats=None):
        # Default hanya prioritas FLAC dan MP3
        if not preferred_formats:
            preferred_formats = ['flac', 'mp3']
            
            # Jika user memilih kualitas tertentu, taruh di depan
            if self.quality in preferred_formats:
                preferred_formats.insert(0, preferred_formats.pop(preferred_formats.index(self.quality)))

        async with self.session.get(track_url) as resp:
            html = await resp.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Cari semua link download
        found_links = {}
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Cek format audio umum
            for fmt in ['flac', 'mp3', 'm4a', 'ogg']:
                if href.lower().endswith(f".{fmt}"):
                    found_links[fmt] = href
        
        # Pilih berdasarkan prioritas
        final_url = None
        final_fmt = 'mp3'
        
        for fmt in preferred_formats:
            if fmt in found_links:
                final_url = found_links[fmt]
                final_fmt = fmt
                break
        
        # Fallback (Jika FLAC tidak ada, ambil MP3, dst)
        if not final_url and found_links:
            # Prioritaskan MP3 sebagai fallback utama jika FLAC gagal
            if 'mp3' in found_links:
                final_fmt = 'mp3'
                final_url = found_links['mp3']
            else:
                final_fmt = list(found_links.keys())[0]
                final_url = found_links[final_fmt]

        if not final_url:
            raise Exception("No download link found on track page.")

        return final_url, final_fmt

khinsider_manager = KhinsiderManager()
