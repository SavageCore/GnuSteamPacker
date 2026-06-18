"""Daemon check: poll Steam for build ID changes and trigger downloads."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from gnusteampacker import config as cfg
from gnusteampacker import credentials, steam_api, worker
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.watchlist import WatchEntry
from gnusteampacker.watchlist import load as load_watchlist
from gnusteampacker.watchlist import save as save_watchlist

log = logging.getLogger(__name__)


def _write_pending_sidecar(item: QueueItem, output_dir: Path) -> None:
    sidecar = {
        "appid": item.appid,
        "game_name": item.game_name,
        "platform": item.platform,
        "branch": item.branch,
        "branch_password": item.branch_password,
        "build_id": item.build_id,
        "build_time": item.build_time,
        "archive_name": item.archive_name,
        "depot_list": item.depot_list,
        "available_platforms": item.available_platforms,
        "downloaded_at": datetime.now(tz=UTC).isoformat(),
    }
    sidecar_path = output_dir / f"{item.archive_name}.pending.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    log.info("Wrote pending sidecar: %s", sidecar_path)


async def _pack_entry(entry: WatchEntry, conf: dict) -> bool:
    output_dir = Path(conf["output_dir"])
    base_auth = credentials.build_auth_override(conf)
    remember_login = bool((base_auth or {}).get("remember_login", conf.get("remember_login", True)))
    username = (base_auth or {}).get("username", credentials.get_username()).strip()
    info_cache: dict = {}
    items = [
        QueueItem(
            appid=entry.appid,
            game_name=entry.name,
            platform=p,
            branch=entry.branch,
            branch_password=entry.branch_password,
        )
        for p in entry.platforms
    ]

    all_ok = True
    for idx, item in enumerate(items):
        per_item_auth = base_auth
        if idx > 0 and remember_login and username:
            per_item_auth = {
                "username": username,
                "password": "",
                "remember_login": remember_login,
            }

        def _update(updated: QueueItem) -> None:
            log.debug(
                "%s %s: %s %.0f%%",
                updated.appid,
                updated.platform,
                updated.status,
                updated.progress * 100,
            )

        await worker.process_item(
            item,
            _update,
            auth_override=per_item_auth,
            info_cache=info_cache,
            write_release_text=False,
        )

        if item.status == Status.COMPLETE:
            _write_pending_sidecar(item, output_dir)
            log.info("Packed %s/%s: %s", entry.appid, item.platform, item.archive_name)
        else:
            log.error(
                "Pack failed for %s/%s: %s %s",
                entry.appid,
                item.platform,
                item.status,
                item.error_detail,
            )
            all_ok = False

    return all_ok


async def _check_all(entries: list[WatchEntry], conf: dict) -> bool:
    any_failed = False

    for entry in entries:
        if not entry.enabled:
            log.debug("Skipping disabled entry: %s (%s)", entry.name, entry.appid)
            continue

        log.info("Checking %s (AppID %s, branch %s)…", entry.name, entry.appid, entry.branch)
        try:
            game_info = await steam_api.get_game_info(entry.appid)
        except Exception as exc:
            log.error("Failed to fetch info for %s: %s", entry.appid, exc)
            entry.last_checked = datetime.now(tz=UTC).isoformat()
            save_watchlist(entries)
            await asyncio.sleep(2)
            continue

        new_build_id = str(
            game_info.get(f"build_{entry.branch}") or game_info.get("build_public") or ""
        )

        if not entry.last_build_id:
            log.info(
                "First check for %s: recorded build %s, not downloading.", entry.name, new_build_id
            )
            entry.last_build_id = new_build_id
        elif new_build_id != entry.last_build_id:
            log.info("New build for %s: %s → %s", entry.name, entry.last_build_id, new_build_id)
            ok = await _pack_entry(entry, conf)
            if ok:
                entry.last_build_id = new_build_id
            else:
                any_failed = True
        else:
            log.info("No change for %s: still at build %s", entry.name, new_build_id)

        entry.last_checked = datetime.now(tz=UTC).isoformat()
        save_watchlist(entries)
        await asyncio.sleep(2)

    return not any_failed


def _setup_logging(conf: dict) -> None:
    import os

    log_file = Path(conf["steamcmd_path"]).parent / "gnusteampacker.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if os.getenv("GNUSTEAMPACKER_DEBUG") else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


async def check_all() -> bool:
    """Public async entry point for in-process checks (e.g. GUI 'Run now' button)."""
    conf = cfg.load()
    entries = load_watchlist()
    if not entries:
        return True
    return await _check_all(entries, conf)


def run_daemon_check() -> int:
    conf = cfg.load()
    _setup_logging(conf)
    entries = load_watchlist()

    if not entries:
        log.info("Watchlist is empty, nothing to check.")
        return 0

    enabled = [e for e in entries if e.enabled]
    log.info("Daemon check: %d/%d entries enabled.", len(enabled), len(entries))

    ok = asyncio.run(_check_all(entries, conf))
    return 0 if ok else 1
