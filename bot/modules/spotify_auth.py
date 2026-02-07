from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from bot import CMD
from bot.helpers.spotify.credentials_manager import HeadlessSpotifyAuth
from bot.helpers.spotify.manager import spotify_manager

# Simpan sesi auth sementara di memori
auth_sessions = {}

@Client.on_message(filters.command("spotify_login") & filters.user(list(Config.ADMINS)))
async def spotify_login_cmd(client, message: Message):
    """
    Command untuk memulai proses login Spotify.
    """
    user_id = message.from_user.id
    auth_handler = HeadlessSpotifyAuth()
    auth_sessions[user_id] = auth_handler
    
    login_url = auth_handler.get_login_url()
    
    msg_text = (
        "<b>🟢 LOGIN SPOTIFY (TANPA PC)</b>\n\n"
        "1. Klik Link ini: <a href='{}'>KLIK DISINI UNTUK LOGIN</a>\n"
        "2. Login akun Spotify Anda dan klik 'Agree/Setuju'.\n"
        "3. Anda akan diarahkan ke halaman yang <b>ERROR (Gagal memuat/Refused to connect)</b>.\n"
        "4. <b>JANGAN PANIK</b>. Lihat Address Bar/Kolom URL Browser Anda.\n"
        "5. Salin <b>SELURUH URL</b> tersebut.\n"
        "6. Kirim ke sini dengan perintah:\n\n"
        "<code>/spotify_token [URL_YANG_DISALIN]</code>"
    ).format(login_url)
    
    await message.reply_text(msg_text, disable_web_page_preview=True)


@Client.on_message(filters.command("spotify_token") & filters.user(list(Config.ADMINS)))
async def spotify_token_cmd(client, message: Message):
    """
    Command untuk memproses URL callback.
    """
    user_id = message.from_user.id
    
    if user_id not in auth_sessions:
        return await message.reply_text("⚠️ Jalankan /spotify_login terlebih dahulu.")
    
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Masukkan URL! Contoh:\n<code>/spotify_token http://127.0.0.1:4381/login?code=...</code>")
    
    url = message.text.split(None, 1)[1].strip()
    auth_handler = auth_sessions[user_id]
    
    status_msg = await message.reply_text("⏳ Memproses token...")
    
    success, result = auth_handler.process_callback_url(url)
    
    if success:
        json_creds = result
        
        # Simpan ke Manager agar langsung aktif tanpa restart
        import os
        creds_path = spotify_manager.credentials_path
        os.makedirs(os.path.dirname(creds_path), exist_ok=True)
        with open(creds_path, "w") as f:
            f.write(json_creds)
            
        # Init ulang manager
        await spotify_manager.initialize()
        
        final_msg = (
            "✅ <b>LOGIN BERHASIL!</b>\n\n"
            "Bot sekarang bisa mendownload dari Spotify.\n\n"
            "⚠️ <b>PENTING UNTUK RENDER:</b>\n"
            "Agar login tidak hilang saat bot restart, Salin JSON di bawah ini dan masukkan ke <b>Environment Variables</b> Render:\n\n"
            f"<b>Key:</b> <code>SPOTIFY_CREDENTIALS_JSON</code>\n"
            f"<b>Value:</b> <code>{json_creds}</code>"
        )
        await status_msg.edit_text(final_msg)
        del auth_sessions[user_id]
    else:
        await status_msg.edit_text(f"❌ <b>GAGAL:</b>\n{result}")

