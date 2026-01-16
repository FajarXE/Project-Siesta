import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...logger import LOGGER

class KhinsiderManager:
    def __init__(self):
        self.session = None
        self.quality = 'flac' 
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
        self.quality = quality

    async def get_album(self, url):
        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch album page: {resp.status}")
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Metadata Dasar
        title = soup.select_one("#pageContent h2")
        title = title.get_text(strip=True) if title else "Unknown Album"
        
        # 2. Metadata Teks (Year, Publisher, Date Added)
        date = "N/A"
        publisher = "N/A"
        date_added = "N/A"
        
        # Cari elemen <b> yang berisi label, lalu ambil teks setelahnya
        # Contoh HTML: <p><b>Published by:</b> STARCHILD<br><b>Date Added:</b> ...</p>
        
        # Ambil Tahun (Year)
        year_node = soup.find('b', string=re.compile(r"Year", re.IGNORECASE))
        if year_node and year_node.next_sibling:
            raw_date = str(year_node.next_sibling).strip()
            match = re.search(r"(\d{4})", raw_date)
            if match:
                date = match.group(1)

        # Ambil Publisher (Published by)
        pub_node = soup.find('b', string=re.compile(r"Published by", re.IGNORECASE))
        if pub_node and pub_node.next_sibling:
            publisher = str(pub_node.next_sibling).strip()

        # Ambil Date Added
        added_node = soup.find('b', string=re.compile(r"Date Added", re.IGNORECASE))
        if added_node and added_node.next_sibling:
            date_added = str(added_node.next_sibling).strip()

        # 3. Ambil Gambar
        images = []
        for img in soup.select("div.albumImage a"):
            href = img.get('href')
            if href:
                full_img_url = href if href.startswith('http') else urljoin(url, href)
                images.append(full_img_url)
        cover_url = images[0] if images else None

        # 4. Parse Tracks
        tracks = []
        table = soup.find("table", id="songlist")
        disc_numbers = set()
        
        if table:
            # Cek Header untuk kolom Disc
            header_row = table.find("tr", id="songlist_header")
            disc_col_idx = -1
            if header_row:
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]
                for i, h in enumerate(headers):
                    if "disc" in h:
                        disc_col_idx = i
                        break

            rows = table.find_all("tr")[1:]
            for row in rows:
                if row.get("id") in ["songlist_footer", "songlist_header"]:
                    continue
                cells = row.find_all("td")
                if len(cells) < 2: continue
                
                link = row.find("a", href=True)
                if not link: continue
                
                track_url = urljoin(url, link['href'])
                track_name = link.get_text(strip=True)
                
                # Nomor Track
                track_num = None
                for cell in cells:
                    txt = cell.get_text(strip=True).replace('.', '')
                    if txt.isdigit() and len(txt) < 4:
                        if disc_col_idx != -1 and cells.index(cell) == disc_col_idx:
                            continue
                        track_num = txt
                        break
                
                # Nomor Disc
                disc_num = 1
                if disc_col_idx != -1 and len(cells) > disc_col_idx:
                    try:
                        d_txt = cells[disc_col_idx].get_text(strip=True)
                        if d_txt.isdigit():
                            disc_num = int(d_txt)
                    except: pass
                
                disc_numbers.add(disc_num)

                tracks.append({
                    'title': track_name,
                    'url': track_url,
                    'track_number': track_num or str(len(tracks) + 1),
                    'disc_number': str(disc_num)
                })

        total_volumes = len(disc_numbers) if disc_numbers else 1

        return {
            'title': title,
            'cover': cover_url,
            'images': images,
            'tracks': tracks,
            'date': date,
            'publisher': publisher,
            'date_added': date_added,
            'totalvolumes': str(total_volumes),
            'explicit': False,
            'provider': 'Khinsider'
        }

    async def get_track_download_url(self, track_url, preferred_formats=None):
        if not preferred_formats:
            preferred_formats = ['flac', 'mp3']
            if self.quality in preferred_formats:
                preferred_formats.insert(0, preferred_formats.pop(preferred_formats.index(self.quality)))

        async with self.session.get(track_url) as resp:
            html = await resp.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        found_links = {}
        for a in soup.find_all('a', href=True):
            href = a['href']
            for fmt in ['flac', 'mp3', 'm4a', 'ogg']:
                if href.lower().endswith(f".{fmt}"):
                    found_links[fmt] = href
        
        final_url = None
        final_fmt = 'mp3'
        
        for fmt in preferred_formats:
            if fmt in found_links:
                final_url = found_links[fmt]
                final_fmt = fmt
                break
        
        if not final_url and found_links:
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
