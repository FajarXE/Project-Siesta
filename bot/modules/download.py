# [GANTI FILE: bot/modules/download.py]

from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio 
import traceback
import random
import aiohttp 

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang

from bot import BOT_QOBUZ_CLIENTS
from bot.tgclient import aio 

# Impor semua manajer
from bot.helpers.deezer.manager import deezer_manager
from bot.helpers.beatport.manager import beatport_manager
from bot.helpers.tidal.manager import tidal_manager
from bot.helpers.kkbox.manager import kkbox_manager
from bot.helpers.beatsource.manager import beatsource_manager
from bot.helpers.soundcloud.manager import soundcloud_manager

# --- TAMBAHAN BARU: Impor Manajer Moov ---
try:
    from bot.helpers.moov.manager import moov_manager
except ImportError:
    moov_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Napster ---
try:
    from bot.helpers.napster.manager import napster_manager
except ImportError:
    napster_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Idagio ---
try:
    from bot.helpers.idagio.manager import idagio_manager
except ImportError:
    idagio_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Nugs.net ---
try:
    from bot.helpers.nugs.manager import nugs_manager
except ImportError:
    nugs_manager = None
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Manajer Bugs ---
try:
    from bot.helpers.bugs.manager import bugs_manager
except ImportError:
    bugs_manager = None
# --- BATAS TAMBAHAN ---

# --- PERBAIKAN IMPOR: Pisahkan Manajer dari Handler ---
# Selalu impor manajer terlebih dahulu
try:
    from bot.helpers.highresaudio.manager import highresaudio_manager, HighResAudioError
except ImportError:
    highresaudio_manager = None
    class HighResAudioError(Exception): pass

# --- TAMBAHAN BARU: Impor Manajer JioSaavn & Gaana ---
try:
    from bot.helpers.jiosaavn.manager import jiosaavn_manager
except ImportError:
    jiosaavn_manager = None

try:
    from bot.helpers.gaana.manager import gaana_manager
except ImportError:
    gaana_manager = None
# --- BATAS TAMBAHAN JIOSAAVN & GAANA ---

# Impor handler secara terpisah
try:
    from bot.helpers.highresaudio.handler import start_highresaudio
except ImportError:
    async def start_highresaudio(*args, **kwargs):
        raise NotImplementedError("Modul HIGHRESAUDIO ('handler.py') belum diimplementasikan.")
# --- BATAS PERBAIKAN ---


from ..helpers.soundcloud.handler import start_soundcloud
from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.beatport.handler import start_beatport

# --- PERBAIKAN: Impor DeezerError ---
try:
    from ..helpers.deezer.manager import DeezerError
except ImportError:
    class DeezerError(Exception): pass
# --- BATAS PERBAIKAN ---

try:
    from ..helpers.kkbox.handler import start_kkbox
except ImportError:
    async def start_kkbox(*args, **kwargs):
        raise NotImplementedError("Modul KKBox ('handler.py') belum diimplementasikan.")
        
try:
    from ..helpers.beatsource.handler import start_beatsource
except ImportError:
    async def start_beatsource(*args, **kwargs):
        raise NotImplementedError("Modul Beatsource ('handler.py') belum diimplementasikan.")

# --- TAMBAHAN BARU: Impor Handler Moov ---
try:
    from ..helpers.moov.handler import start_moov
except ImportError:
    async def start_moov(*args, **kwargs):
        raise NotImplementedError("Modul Moov ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler Napster ---
try:
    from ..helpers.napster.handler import start_napster
    # --- TAMBAHAN BARU: Impor error Napster ---
    from ..helpers.napster.manager import NapsterError
except ImportError:
    async def start_napster(*args, **kwargs):
        raise NotImplementedError("Modul Napster ('handler.py') belum diimplementasikan.")
    class NapsterError(Exception): pass
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler Idagio ---
try:
    from ..helpers.idagio.handler import start_idagio
except ImportError:
    async def start_idagio(*args, **kwargs):
        raise NotImplementedError("Modul Idagio ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler Nugs.net ---
try:
    from ..helpers.nugs.handler import start_nugs
except ImportError:
    async def start_nugs(*args, **kwargs):
        raise NotImplementedError("Modul Nugs.net ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler Bugs ---
try:
    from ..helpers.bugs.handler import start_bugs
    from ..helpers.bugs.manager import BugsError
except ImportError:
    async def start_bugs(*args, **kwargs):
        raise NotImplementedError("Modul Bugs ('handler.py') belum diimplementasikan.")
    class BugsError(Exception): pass
# --- BATAS TAMBAHAN ---

# --- TAMBAHAN BARU: Impor Handler JioSaavn & Gaana ---
try:
    from ..helpers.jiosaavn.handler import start_jiosaavn
except ImportError as e:
    err_jio = str(e)
    LOGGER.error(f"Gagal Import JioSaavn: {err_jio}")
    async def start_jiosaavn(*args, **kwargs):
        raise NotImplementedError(f"Modul JioSaavn Rusak: {err_jio}")

try:
    from ..helpers.gaana.handler import start_gaana
except ImportError as e:
    err_gaana = str(e)
    LOGGER.error(f"Gagal Import Gaana: {err_gaana}")
    async def start_gaana(*args, **kwargs):
        raise NotImplementedError(f"Modul Gaana Rusak: {err_gaana}")


try:
    from ..helpers.gaana.handler import start_gaana
except ImportError:
    async def start_gaana(*args, **kwargs):
        raise NotImplementedError("Modul Gaana ('handler.py') belum diimplementasikan.")
# --- BATAS TAMBAHAN ---


from ..helpers.message import send_message, check_user, fetch_user_details, edit_message


# --- FUNGSI BARU UNTUK MEMBUKA SHORTLINK ---
async def resolve_shortlink(link: str) -> str:
    """
    Membuka shortlink dengan penanganan Manual Redirect untuk menangkap fragment (#) URL.
    """
    target_domains = ["2nu.gs", "app.moov.hk", "moov.hk/r/", "bit.ly", "t.co", "youtu.be"]
    
    if any(d in link for d in target_domains):
        try:
            # Gunakan User-Agent Desktop
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                current_url = link
                # Lakukan Loop Redirect Manual (Max 5 kali)
                for _ in range(5):
                    async with session.get(current_url, allow_redirects=False) as resp:
                        if 'Location' in resp.headers:
                            new_url = resp.headers['Location']
                            
                            # Logika Khusus Moov: Tangkap URL yang ada '/album/' atau '/song/'
                            # meskipun itu ada di dalam redirect sementara
                            if "moov.hk" in new_url and ("/album/" in new_url or "/song/" in new_url):
                                LOGGER.info(f"Shortlink Detected Target: {link} -> {new_url}")
                                return new_url
                            
                            # Handle Relative URL
                            if new_url.startswith("/"):
                                from urllib.parse import urljoin
                                new_url = urljoin(current_url, new_url)
                            
                            current_url = new_url
                        else:
                            # Stop jika tidak ada redirect lagi
                            break
                
                # Jika loop selesai, kembalikan URL terakhir yang didapat
                LOGGER.info(f"Shortlink Final: {link} -> {current_url}")
                return current_url

        except Exception as e:
            LOGGER.error(f"Gagal me-resolve shortlink {link}: {e}")
            return link 
    return link
# --- BATAS FUNGSI BARU ---


async def run_download_task(link: str, user: dict):
    task_successful = False
    try:
        user['bot_msg'] = await send_message(user, 'Memulai tugas...')
        
        resolved = await resolve_shortlink(link)
        if resolved != link:
             link = resolved
             user['link'] = link

        await start_link(link, user)
        task_successful = True
 
    except asyncio.CancelledError:
        LOGGER.info(f"Tugas untuk {user['user_id']} dibatalkan (mungkin shutdown).")
        await send_message(user, "Tugas dibatalkan.")
        await asyncio.sleep(5) 
            
    except Exception as e:
        error_str = str(e)
        # --- MODIFIKASI: Deteksi Error yang Dapat Dimaafkan (Tanpa Traceback) ---
        is_handled_error = False
        if "not available in any" in error_str or \
           "Maaf, tidak ada akun" in error_str or \
           "NotImplementedError" in error_str or \
           "URL Deezer tidak valid" in error_str or \
           "Item tidak tersedia di semua" in error_str or \
           "Track not available" in error_str or \
           "Stream key kosong" in error_str or \
           "Region Locked" in error_str or \
           isinstance(e, NapsterError) or \
           isinstance(e, BugsError) or \
           (highresaudio_manager and isinstance(e, HighResAudioError)) or \
           isinstance(e, DeezerError): 
            is_handled_error = True
        # --- BATAS MODIFIKASI ---
        
        error_message = f"Tugas Gagal: {e}" if is_handled_error else f"Tugas Gagal: Terjadi error.\n`{e}`"

        if is_handled_error:
             # Log sebagai warning biasa, tanpa traceback panjang
             LOGGER.warning(f"Download Task Gagal (Handled): {e}")
        else:
             # Log sebagai error fatal dengan traceback
             LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")

        try:
            await edit_message(user['bot_msg'], error_message)
        except:
            pass 
            
    finally:
        await cleanup(user)
        try:
            if task_successful:
                await aio.delete_messages(user['chat_id'], user['bot_msg'].id)
        except:
            pass


@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg:Message):
    if await check_user(msg=msg):
        
        text_content = ""
        reply = False
        
        if msg.reply_to_message:
            text_content = msg.reply_to_message.text
            reply = True
        else:
            text_content = msg.text
            reply = False

        link = ""
        try:
            parts = text_content.split()
            for part in parts:
                if part.startswith("http://") or part.startswith("https://"):
                    link = part 
                    break 

            if not link:
                raise IndexError
                
        except IndexError:
            return await send_message(msg, lang.s.ERR_NO_LINK)

        if not link:
            return await send_message(msg, lang.s.ERR_LINK_RECOGNITION)
        
        user = await fetch_user_details(msg, reply)
        
        try:
            resolved_link = await resolve_shortlink(link)
            if resolved_link != link:
                link = resolved_link 
        except Exception: pass 
        
        user['link'] = link
        asyncio.create_task(run_download_task(link, user))
        

async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "http://www.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    beatport = ["https://www.beatport.com", "http://www.beatport.com", "beatport.com"]
    beatsource = ["https://www.beatsource.com", "beatsource.com"]
    
    soundcloud = [
        "https://soundcloud.com", "soundcloud.com", 
        "https://on.soundcloud.com", "on.soundcloud.com",
        "https://m.soundcloud.com", "m.soundcloud.com"
    ]
    
    kkbox = ["https://play.kkbox.com", "https://www.kkbox.com", "kkbox.com"]
    
    # --- TAMBAHAN BARU: URL Moov ---
    moov = ["https://moov.hk", "https://app.moov.hk", "moov.hk", "app.moov.hk"]
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: URL Napster ---
    napster = [
        "https://app.napster.com", "napster.com", "http://app.napster.com", 
        "https://play.napster.com", "play.napster.com", 
        "https://web.napster.com", "web.napster.com"
    ]
    # --- BATAS TAMBAHAN ---
    
    # --- TAMBAHAN BARU: URL Idagio ---
    idagio = ["https://www.idagio.com", "idagio.com", "https://app.idagio.com"]
    # --- BATAS TAMBAHAN ---
    
    # --- MODIFIKASI: URL Nugs.net ---
    nugs = ["https://play.nugs.net", "play.nugs.net", "https://streamapi.nugs.net"]
    # --- BATAS MODIFIKASI ---

    # --- PERBAIKAN: URL Bugs (Tambahkan m.bugs.co.kr) ---
    bugs = ["https://music.bugs.co.kr", "music.bugs.co.kr", "https://m.bugs.co.kr", "m.bugs.co.kr"]
    # --- BATAS PERBAIKAN ---

    # --- TAMBAHAN BARU: URL HIGHRESAUDIO ---
    highresaudio = ["https://www.highresaudio.com", "highresaudio.com"]
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: URL JioSaavn & Gaana ---
    jiosaavn = ["https://www.jiosaavn.com", "jiosaavn.com"]
    gaana = ["https://gaana.com", "gaana.com"]
    # --- BATAS TAMBAHAN ---
    
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        
        if not tidal_manager.clients:
            raise Exception("Maaf, tidak ada akun Tidal bot yang aktif saat ini.")

        clients_list = list(tidal_manager.clients)
        if len(clients_list) > 1:
            random.shuffle(clients_list)
        last_error = None
        for client in clients_list:
            try:
                user['tidal_api'] = client
                await start_tidal(link, user)
                LOGGER.info(f"Tidal: Unduhan berhasil menggunakan akun User ID {client.user_id}")
                return
            except Exception as e:
                error_str = str(e).lower()
                if 'asset is not ready' in error_str or \
                   'not available in your region' in error_str or \
                   'region-locked' in error_str:
                    LOGGER.warning(f"Tidal: Akun {client.user_id} gagal (Region Lock): {e}. Mencoba akun berikutnya...")
                    last_error = e
                    continue
                else:
                    LOGGER.error(f"Tidal: Akun {client.user_id} gagal (Fatal): {e}")
                    raise e
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Tidal yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Tidal karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        
        if not deezer_manager.clients:
            raise Exception("Maaf, tidak ada akun Deezer bot yang aktif saat ini.")
        
        clients_list = random.sample(deezer_manager.clients, len(deezer_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['deezer_api'] = client 
                await start_deezer(link, user)
                LOGGER.info(f"Deezer: Unduhan berhasil menggunakan ARL ID {client.user['USER']['USER_ID']}")
                return 
            except Exception as e:
                # --- PERBAIKAN LOGIC RETRY ---
                error_str = str(e).lower()
                is_retryable = False
                
                # Cek DeezerError atau pesan error string
                if isinstance(e, DeezerError) or \
                   "not available in your country" in error_str or \
                   "not available by your subscription" in error_str or \
                   "track not available" in error_str:
                    is_retryable = True

                if is_retryable:
                    LOGGER.warning(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Region/Sub Lock): {e}. Mencoba ARL berikutnya...")
                    last_error = e
                    continue 
                else:
                    # Error fatal lainnya (misal: parsing gagal)
                    LOGGER.error(f"Deezer: ARL ID {client.user['USER']['USER_ID']} gagal (Fatal): {e}")
                    raise e 
        if last_error:
            # Ini akan ditangkap di run_download_task tanpa traceback
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Deezer yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Deezer karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        if not BOT_QOBUZ_CLIENTS:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        clients_list = list(BOT_QOBUZ_CLIENTS.values())
        random.shuffle(clients_list)
        user['qobuz_clients_list'] = clients_list
        await start_qobuz(link, user)

    elif link.startswith(tuple(beatport)):
        user['provider'] = 'Beatport'
        
        if not beatport_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatport bot yang aktif saat ini.")

        clients_list = random.sample(beatport_manager.clients, len(beatport_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['beatport_api'] = client 
                await start_beatport(link, user)
                LOGGER.info(f"Beatport: Unduhan berhasil menggunakan akun.") 
                return 
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str:
                    LOGGER.warning(f"Beatport: Akun gagal (Region/Sub Lock/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatport: Akun gagal (Fatal): {e}")
                    raise e 
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatport yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatport karena alasan yang tidak diketahui setelah mencoba semua akun.")

    elif link.startswith(tuple(beatsource)):
        user['provider'] = 'Beatsource'
        
        if not beatsource_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatsource bot yang aktif saat ini.")

        clients_list = random.sample(beatsource_manager.clients, len(beatsource_manager.clients))
        last_error = None

        for client in clients_list:
            try:
                user['beatsource_api'] = client 
                await start_beatsource(link, user)
                
                LOGGER.info(f"Beatsource: Unduhan berhasil menggunakan akun.") 
                return 
                
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str or \
                   "login gagal" in error_str:
                    LOGGER.warning(f"Beatsource: Akun gagal (Region/Sub Lock/Auth/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatsource: Akun gagal (Fatal): {e}")
                    raise e 
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatsource yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatsource karena alasan yang tidak diketahui setelah mencoba semua akun.")
    
    elif link.startswith(tuple(soundcloud)):
        user['provider'] = 'Soundcloud'
        
        client = soundcloud_manager.get_client()
        if not client:
            raise Exception("Maaf, modul Soundcloud bot tidak aktif saat ini (Token salah atau hilang).")

        try:
            user['soundcloud_api'] = client
            await start_soundcloud(link, user)
            LOGGER.info(f"Soundcloud: Unduhan berhasil.") 
            return 
            
        except Exception as e:
            LOGGER.error(f"Soundcloud: Tugas gagal (Fatal): {e}")
            raise e 
    
    elif link.startswith(tuple(kkbox)):
        user['provider'] = 'KKBox'
        
        if not kkbox_manager.clients:
            raise Exception("Maaf, tidak ada akun KKBox bot yang aktif saat ini.")

        clients_list = random.sample(kkbox_manager.clients, len(kkbox_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['kkbox_api'] = client
                await start_kkbox(link, user)
                LOGGER.info(f"KKBox: Unduhan berhasil menggunakan akun.") 
                return
            except Exception as e:
                error_str = str(e).lower()
                if "unsupported region" in error_str or \
                   "account expired" in error_str or \
                   "quality not available" in error_str or \
                   "incorrect password" in error_str or \
                   "email not found" in error_str:
                    LOGGER.warning(f"KKBox: Akun gagal (Region/Sub/Auth): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue
                else:
                    LOGGER.error(f"KKBox: Akun gagal (Fatal): {e}")
                    raise e
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun KKBox yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh KKBox karena alasan yang tidak diketahui setelah mencoba semua akun.")

    # --- TAMBAHAN BARU: Blok Moov ---
    elif link.startswith(tuple(moov)):
        user['provider'] = 'Moov'
        
        if not moov_manager or not moov_manager.clients:
            raise Exception("Maaf, tidak ada akun Moov bot yang aktif saat ini.")

        client = moov_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Moov yang tersedia (semua gagal login?).")

        try:
            user['moov_api'] = client
            await start_moov(link, user)
            LOGGER.info(f"Moov: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Moov: Tugas gagal (Fatal): {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Napster ---
    elif link.startswith(tuple(napster)):
        user['provider'] = 'Napster'
        
        if not napster_manager or not napster_manager.clients:
            raise Exception("Maaf, tidak ada akun Napster bot yang aktif saat ini.")

        client = napster_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Napster yang tersedia (semua gagal login?).")

        try:
            user['napster_api'] = client
            await start_napster(link, user)
            LOGGER.info(f"Napster: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            error_str = str(e).lower()
            if isinstance(e, NapsterError) or "tidak ditemukan" in error_str or "tidak tersedia" in error_str:
                LOGGER.error(f"Napster: Tugas gagal (Dapat Ditangani): {e}")
                raise e
            else:
                LOGGER.error(f"Napster: Tugas gagal (Fatal): {e}")
                raise e
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Idagio ---
    elif link.startswith(tuple(idagio)):
        user['provider'] = 'Idagio'
        
        if not idagio_manager or not idagio_manager.clients:
            raise Exception("Maaf, tidak ada akun Idagio bot yang aktif saat ini.")

        client = idagio_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Idagio yang tersedia (semua gagal login?).")

        try:
            user['idagio_api'] = client
            await start_idagio(link, user)
            LOGGER.info(f"Idagio: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Idagio: Tugas gagal (Fatal): {e}")
            raise e
    # --- BATAS TAMBAHAN ---
    
    # --- TAMBAHAN BARU: Blok Nugs.net ---
    elif link.startswith(tuple(nugs)):
        user['provider'] = 'Nugs.net'
        
        if not nugs_manager or not nugs_manager.clients:
            raise Exception("Maaf, tidak ada akun Nugs.net bot yang aktif saat ini.")

        client = nugs_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Nugs.net yang tersedia (semua gagal login?).")

        try:
            user['nugs_api'] = client
            await start_nugs(link, user)
            LOGGER.info(f"Nugs.net: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Nugs.net: Tugas gagal (Fatal): {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Bugs ---
    elif link.startswith(tuple(bugs)):
        user['provider'] = 'Bugs'
        
        if not bugs_manager or not bugs_manager.clients:
            raise Exception("Maaf, tidak ada akun Bugs bot yang aktif saat ini.")

        client = bugs_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Bugs yang tersedia (semua gagal login?).")

        try:
            user['bugs_api'] = client
            await start_bugs(link, user)
            LOGGER.info(f"Bugs: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            error_str = str(e).lower()
            if isinstance(e, BugsError) or "tidak ditemukan" in error_str or "tidak tersedia" in error_str:
                LOGGER.error(f"Bugs: Tugas gagal (Dapat Ditangani): {e}")
                raise e 
            else:
                LOGGER.error(f"Bugs: Tugas gagal (Fatal): {e}")
                raise e 
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok HIGHRESAUDIO ---
    elif link.startswith(tuple(highresaudio)):
        user['provider'] = 'HIGHRESAUDIO'
        
        if not highresaudio_manager or not highresaudio_manager.clients:
            raise Exception("Maaf, tidak ada akun HIGHRESAUDIO bot yang aktif saat ini.")

        client = highresaudio_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien HIGHRESAUDIO yang tersedia (semua gagal login?).")

        try:
            user['highresaudio_api'] = client
            await start_highresaudio(link, user)
            LOGGER.info(f"HIGHRESAUDIO: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            if isinstance(e, HighResAudioError):
                LOGGER.error(f"HIGHRESAUDIO: Tugas gagal (Dapat Ditangani): {e}")
                raise e 
            else:
                LOGGER.error(f"HIGHRESAUDIO: Tugas gagal (Fatal): {e}")
                raise e 
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok JioSaavn ---
    elif link.startswith(tuple(jiosaavn)):
        user['provider'] = 'JioSaavn'
        if not jiosaavn_manager:
             raise Exception("Modul JioSaavn tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_jiosaavn(link, user)
            LOGGER.info("JioSaavn: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"JioSaavn Gagal: {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    # --- TAMBAHAN BARU: Blok Gaana ---
    elif link.startswith(tuple(gaana)):
        user['provider'] = 'Gaana'
        if not gaana_manager:
             raise Exception("Modul Gaana tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_gaana(link, user)
            LOGGER.info("Gaana: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"Gaana Gagal: {e}")
            raise e
    # --- BATAS TAMBAHAN ---

    else:
        LOGGER.warning(f"Link tidak dikenali: {link}")
        raise Exception(f"Link tidak dikenali. Bot tidak tahu cara mengunduh dari: {link}")

