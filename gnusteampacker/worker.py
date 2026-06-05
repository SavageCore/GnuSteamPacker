"""Async download pipeline: info fetch → steamcmd → vdf_clean → dd manifests → compress."""

import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from gnusteampacker import (
    compressor,
    credentials,
    depotdownloader,
    folder_organiser,
    release_text,
    steam_api,
    steamcmd,
    vdf_cleaner,
)
from gnusteampacker import config as cfg
from gnusteampacker.queue_model import QueueItem, Status

log = logging.getLogger(__name__)

UpdateCB = Callable[[QueueItem], None]

_MANIFEST_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")


async def process_item(
    item: QueueItem, update_cb: UpdateCB, steam_guard_code: str | None = None
) -> None:
    conf = cfg.load()
    sc_path = Path(conf["steamcmd_path"])
    dd_path = Path(conf["depotdownloader_path"])
    output_base = Path(conf["output_dir"])
    compression_level = int(conf.get("compression_level", 5))
    compression_threads = int(conf.get("compression_threads", 1))

    def push(status: Status, progress: float = 0.0, detail: str = "") -> None:
        item.status = status
        item.progress = progress
        item.error_detail = detail
        update_cb(item)

    # ── 1. Ensure tools are available ─────────────────────────────────────
    if conf.get("steamcmd_auto_download", True):
        try:
            await steamcmd.ensure_steamcmd(sc_path, lambda msg: push(Status.GETINFO, 0, msg))
        except Exception as e:
            push(Status.FAIL, detail=f"SteamCMD install failed: {e}")
            return

    if conf.get("depotdownloader_auto_download", True):
        try:
            await depotdownloader.ensure_depotdownloader(
                dd_path, lambda msg: push(Status.GETINFO, 0, msg)
            )
        except Exception as e:
            push(Status.FAIL, detail=f"DepotDownloader install failed: {e}")
            return

    # ── 2. Fetch game info and initial depot list ──────────────────────────
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

    # ── 3. Download via SteamCMD ───────────────────────────────────────────
    push(Status.DOWNLOADING, 0.0)
    username = credentials.get_username()
    password = credentials.get_password()
    install_dir = output_base / f"{item.appid}_{item.platform}"

    def sc_progress(pct: float, line: str) -> None:
        if "Logging in" in line:
            push(Status.AUTHENTICATING)
        else:
            push(Status.DOWNLOADING, pct)

    try:
        ok, reason = await steamcmd.run_download(
            item, sc_path, username, password, install_dir, sc_progress
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

    # Guard: SteamCMD places game files at install_dir/ root (ACFs at steamapps/).
    root_entries = [e for e in install_dir.iterdir() if e.name != "steamapps"]
    log.debug("install_dir root entries (excl. steamapps): %d", len(root_entries))
    if not root_entries:
        push(Status.FAIL, detail="Download completed but no game files found in staging directory")
        return

    # ── 4. Sanitise ACF files ──────────────────────────────────────────────
    push(Status.CLEANING, 0.0)
    try:
        vdf_cleaner.clean_steamapps(install_dir / "steamapps")
    except Exception as e:
        log.warning("vdf_cleaner failed: %s", e)

    # ── 5. Fetch manifest files via DepotDownloader ────────────────────────
    push(Status.CLEANING, 0.5)
    try:
        ok, reason = await depotdownloader.run_manifest_only(
            item, dd_path, username, password, install_dir
        )
        if not ok:
            log.warning(
                "DepotDownloader manifest-only failed (%s) — depotcache will be empty", reason
            )
    except Exception as e:
        log.warning("DepotDownloader manifest-only error: %s — depotcache will be empty", e)

    # ── 6. Rebuild depot list with real manifest GIDs ─────────────────────
    dd_cache = install_dir / ".DepotDownloader"
    if dd_cache.exists():
        manifest_overrides: dict[str, str] = {}
        for f in dd_cache.glob("*.manifest"):
            m = _MANIFEST_RE.match(f.name)
            if m:
                manifest_overrides[m.group(1)] = m.group(2)
        if manifest_overrides:
            item.depot_list = release_text.build_depot_list(
                game_info, depot_names, item.branch, manifest_overrides=manifest_overrides
            )

    # ── 7. Promote manifest files to depotcache/ ──────────────────────────
    push(Status.CLEANING, 1.0)
    folder_organiser.reorganise(install_dir, item.appid)

    # ── 8. Compress ────────────────────────────────────────────────────────
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

    # ── 9. Write BBCode release text ───────────────────────────────────────
    txt_path = output_folder / (item.archive_name + ".txt")
    txt_path.write_text(release_text.generate(item), encoding="utf-8")

    # ── 10. Remove staging directory ───────────────────────────────────────
    shutil.rmtree(install_dir, ignore_errors=True)

    push(Status.COMPLETE, 1.0)
