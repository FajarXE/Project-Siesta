import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List

from config import Config

from bot.helpers.message import send_message, edit_message
from bot.helpers.uploder import track_upload


async def start_beatport(link: str, user: Dict) -> None:
    """
    Run OrpheusDL (orpheus.py) as a submodule to download Beatport content for `link`.

    Behaviour:
    - Merge and write a temporary `settings.json` into the OrpheusDL folder based on
      `bot/helpers/OrpheusDL/config/settings.json`, overriding download path and
      beatport credentials from `config.Config`.
    - Run `orpheus.py <link>` as a subprocess with cwd set to the OrpheusDL folder.
    - Collect downloaded files from a per-task download directory and call
      `track_upload(user)` for each file so files are sent to Telegram same as other
      provider handlers.

    The function is async so `bot/modules/download.py` can `await start_beatport(link, user)`.
    """

    # locate OrpheusDL package (assumed sibling of this `beatport` folder)
    base = Path(__file__).parent.parent / "orpheusdl"
    orpheus_py = base / "orpheus.py"
    config_src = base / "config" / "settings.json"

    if not orpheus_py.exists() or not config_src.exists():
        await send_message(user, "OrpheusDL 或設定檔未找到，無法下載 Beatport。")
        return

    # load orpheus default settings (we will merge and override only necessary fields)
    try:
        with open(config_src, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        await send_message(user, f"讀取 Orpheus 設定檔失敗：{e}")
        return

    # determine project root and download base directory (make absolute)
    project_root = Path.cwd().resolve()

    # Config.WORK_DIR may be relative; resolve against project_root
    work_dir = Path(getattr(Config, "WORK_DIR", "./bot/") or "./bot/")
    if not work_dir.is_absolute():
        work_dir = (project_root / work_dir).resolve()

    # Prefer DOWNLOAD_BASE_DIR or LOCAL_STORAGE; make absolute
    dl_base_raw = getattr(Config, "DOWNLOAD_BASE_DIR", None) or getattr(Config, "LOCAL_STORAGE", None)
    if not dl_base_raw:
        dl_base_raw = str(work_dir / getattr(Config, "DOWNLOADS_FOLDER", "DOWNLOADS"))

    dl_base = Path(dl_base_raw)
    if not dl_base.is_absolute():
        dl_base = (project_root / dl_base).resolve()

    # create per-task download dir
    ts = int(time.time())
    tmp_download = dl_base / f"orpheus_{user.get('user_id','anon')}_{ts}"
    try:
        tmp_download.mkdir(parents=True, exist_ok=True)
    except Exception:
        await send_message(user, f"無法建立臨時下載資料夾 {tmp_download}")
        return

    # set download path absolute in orpheus config
    cfg.setdefault("global", {}).setdefault("general", {})
    cfg["global"]["general"]["download_path"] = str(tmp_download.resolve()) + "/"

    # set Beatport credentials from Config (email/password) and downloader
    bp_email = Config.BEATPORT_EMAIL
    bp_pass = Config.BEATPORT_PASSWORD
    if not bp_email or not bp_pass:
        # inform user and cleanup
        await send_message(user, "請先在環境或設定中設定 BEATPORT_EMAIL 與 BEATPORT_PASSWORD。")
        try:
            shutil.rmtree(tmp_download)
        except Exception:
            pass
        return

    cfg.setdefault("modules", {}).setdefault("beatport", {})
    # set both email/username keys to be tolerant of orpheus expectations
    # cfg["modules"]["beatport"]["email"] = bp_email
    cfg["modules"]["beatport"]["username"] = bp_email
    cfg["modules"]["beatport"]["password"] = bp_pass
    # cfg["modules"]["beatport"]["downloader"] = "hbeatport"

    # backup existing settings.json inside OrpheusDL if present, write atomically
    target_settings = base / "settings.json"
    backup = None
    if target_settings.exists():
        backup = base / f"settings.json.bak.{ts}"
        try:
            target_settings.rename(backup)
        except Exception:
            backup = None

    temp_write = base / f"settings.json.tmp.{ts}"
    try:
        with open(temp_write, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        temp_write.replace(target_settings)
    except Exception as e:
        # restore backup if needed
        if temp_write.exists():
            try:
                temp_write.unlink()
            except Exception:
                pass
        if backup and backup.exists():
            try:
                backup.rename(target_settings)
            except Exception:
                pass
        await send_message(user, f"寫入 Orpheus 設定失敗：{e}")
        try:
            shutil.rmtree(tmp_download)
        except Exception:
            pass
        return

    status_msg = await send_message(user, f"開始 Beatport 下載：{link}")

    # run orpheus.py with timeout
    timeout = getattr(Config, "ORPHEUSDL_TIMEOUT", 3600)
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "orpheus.py", link,
            cwd=str(base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await edit_message(user, "Orpheus 下載逾時，已終止任務。")
            return

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")
            await edit_message(user, f"Orpheus 錯誤，無法下載：\n{err[:1500]}")
            return

        # collect downloaded files
        files: List[Path] = [p for p in tmp_download.rglob("*") if p.is_file()]
        if not files:
            await edit_message(user, "下載完成但找不到產生的檔案。")
            return

        # upload files via existing uploader (same behaviour as other handlers)
        for fpath in sorted(files):
            user['filepath'] = str(fpath)
            # let track_upload handle sending to Telegram / rclone etc.
            try:
                await track_upload(user)
            except Exception as e:
                # do not fail entire flow for one file; report and continue
                await send_message(user, f"上傳檔案失敗 {fpath.name}: {e}")

        await edit_message(user, "Beatport 下載並上傳完成。")

    except Exception as e:
        await edit_message(user, f"執行 Orpheus 例外：{e}")
    finally:
        # restore original settings.json if backed up
        try:
            if target_settings.exists():
                target_settings.unlink()
            if backup and backup.exists():
                backup.rename(target_settings)
        except Exception:
            pass

        # cleanup temp downloads
        try:
            shutil.rmtree(tmp_download)
        except Exception:
            pass

        # delete status message if exists
        try:
            await status_msg.delete()
        except Exception:
            pass
