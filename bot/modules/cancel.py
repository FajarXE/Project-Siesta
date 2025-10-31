from pyrogram import Client, filters
# Impor CMD dan dictionary task kita
from bot import cmd, ACTIVE_DOWNLOAD_TASKS
from bot.helpers.message import send_message, check_user
from bot.logger import LOGGER

@Client.on_message(filters.command(cmd.CANCEL))
async def cancel_task(c, msg):
    if not await check_user(msg=msg):
        return

    user_id = msg.from_user.id
    
    # Cek apakah pengguna memiliki tugas aktif
    task_to_cancel = ACTIVE_DOWNLOAD_TASKS.get(user_id)
    
    if task_to_cancel:
        try:
            # Batalkan task
            task_to_cancel.cancel()
            
            # Hapus dari dictionary (meskipun run_download_task juga melakukannya)
            ACTIVE_DOWNLOAD_TASKS.pop(user_id, None) 
            
            await send_message(msg, "Tugas Anda yang sedang berjalan telah diminta untuk berhenti.")
            LOGGER.info(f"Tugas untuk {user_id} dibatalkan oleh perintah /cancel.")
        except Exception as e:
            await send_message(msg, f"Gagal membatalkan tugas: {e}")
            LOGGER.error(f"Gagal membatalkan tugas untuk {user_id}: {e}")
    else:
        await send_message(msg, "Anda tidak memiliki tugas yang sedang berjalan untuk dibatalkan.")
