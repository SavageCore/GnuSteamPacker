"""Async download pipeline: info fetch → steamcmd → clean → compress."""

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from gnusteampacker import compressor, credentials, release_text, steam_api, steamcmd, vdf_cleaner
from gnusteampacker import config as cfg
from gnusteampacker.queue_model import QueueItem, Status

log = logging.getLogger(__name__)

UpdateCB = Callable[[QueueItem], None]


async def process_item(
    item: QueueItem, update_cb: UpdateCB, steam_guard_code: str | None = None
) -> None:
    conf = cfg.load()
    steamcmd_path = Path(conf["steamcmd_path"])
    output_base = Path(conf["output_dir"])
    compression_level = int(conf.get("compression_level", 5))
    compression_threads = int(conf.get("compression_threads", 1))

    def push(status: Status, progress: float = 0.0, detail: str = "") -> None:
        item.status = status
        item.progress = progress
        item.error_detail = detail
        update_cb(item)

    # ── 1. Ensure SteamCMD is available ────────────────────────────────────
    if conf.get("steamcmd_auto_download", True):
        try:
            await steamcmd.ensure_steamcmd(steamcmd_path, lambda msg: push(Status.GETINFO, 0, msg))
        except Exception as e:
            push(Status.FAIL, detail=f"SteamCMD install failed: {e}")
            return

    # ── 2. Fetch game info and depot list ──────────────────────────────────
    push(Status.GETINFO)
    try:
        depot_names = await steam_api.fetch_depot_names()
        game_info = await steam_api.get_game_info(item.appid)
        item.game_name = game_info["name"]
        item.build_id = game_info.get(f"build_{item.branch}") or game_info.get("build_public", "")
        item.build_time = game_info.get(f"time_{item.branch}") or game_info.get("time_public", "")
        item.depot_list = release_text.build_depot_list(game_info, depot_names, item.branch)
    except Exception as e:
        push(Status.FAIL, detail=f"Info fetch failed: {e}")
        return

    # ── 3. Download ────────────────────────────────────────────────────────
    push(Status.DOWNLOADING, 0.0)
    username = credentials.get_username()
    password = credentials.get_password()
    install_dir = output_base / f"{item.appid}_{item.platform}"

    def dl_progress(pct: float, line: str) -> None:
        if "Logging in using" in line:
            push(Status.AUTHENTICATING)
        else:
            push(Status.DOWNLOADING, pct)

    try:
        ok, reason = await steamcmd.run_download(
            item, steamcmd_path, username, password, install_dir, dl_progress, steam_guard_code
        )
    except Exception as e:
        push(Status.FAIL, detail=str(e))
        return

    if not ok:
        status_map = {
            "nosub": Status.NOSUB,
            "ratelimited": Status.RATELIMITED,
            "badlogin": Status.BADLOGIN,
            "steamguard": Status.STEAMGUARD,
        }
        push(status_map.get(reason, Status.FAIL), detail=reason)
        return

    # Guard: fail fast if SteamCMD ran but downloaded nothing.
    # Game files install directly into install_dir (not under steamapps/common);
    # steamapps/ is only SteamCMD metadata so we exclude it from the check.
    game_entries = (
        [p for p in install_dir.iterdir() if p.name != "steamapps"]
        if install_dir.exists() else []
    )
    log.debug("install_dir non-steamapps entries: %s", [p.name for p in game_entries])
    if not game_entries:
        push(Status.FAIL, detail="Download completed but no game files found in install directory")
        return

    # ── 4. Clean sensitive data ────────────────────────────────────────────
    push(Status.CLEANING, 1.0)
    steamapps_dir = install_dir / "steamapps"
    if steamapps_dir.exists():
        vdf_cleaner.clean_steamapps(steamapps_dir)

    # ── 5. Compress ────────────────────────────────────────────────────────
    push(Status.COMPRESSING, 0.0)
    output_folder = output_base / item.archive_name
    try:
        await compressor.compress(
            source_dir=install_dir,
            archive_name=item.archive_name,
            output_dir=output_folder,
            progress_cb=lambda line: push(Status.COMPRESSING, item.progress),
            level=compression_level,
            threads=compression_threads,
        )
    except Exception as e:
        push(Status.FAIL, detail=str(e))
        return

    # ── 6. Write BBCode release text ───────────────────────────────────────
    txt_path = output_folder / (item.archive_name + ".txt")
    txt_path.write_text(release_text.generate(item), encoding="utf-8")

    # ── 7. Remove staging directory ────────────────────────────────────────
    shutil.rmtree(install_dir, ignore_errors=True)

    push(Status.COMPLETE, 1.0)
