"""Daemon check: poll Steam for build ID changes and trigger downloads."""

import asyncio
import json
import logging
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from gnusteampacker import config as cfg
from gnusteampacker import credentials, steam_api, worker
from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem, Status
from gnusteampacker.watchlist import WatchEntry
from gnusteampacker.watchlist import load as load_watchlist
from gnusteampacker.watchlist import save as save_watchlist

log = logging.getLogger(__name__)


def _missing_platforms(entry: WatchEntry, build_id: str, conf: dict) -> list[str]:
    """Platforms in entry.platforms with no archive on disk for build_id.

    The very-first-ever check for an entry is handled separately (records the
    build without downloading) - by the time this runs, that has already
    happened at least once, so any platform still missing here (including "no
    platform has ever been fetched for this build") should be filled in.
    """
    output_dir = Path(entry.output_dir or conf["output_dir"])
    missing: list[str] = []
    for p in entry.platforms:
        item = QueueItem(
            appid=entry.appid,
            game_name=entry.name,
            platform=p,
            branch=entry.branch,
            branch_password=entry.branch_password,
            build_id=build_id,
        )
        name = f"{item.archive_name}.7z"
        # Pending / processed-without-upload archives live in output_dir;
        # processed-with-upload archives are moved into output_dir/<safe_name>/.
        exists = (output_dir / name).exists() or (output_dir / item.safe_name / name).exists()
        if not exists:
            missing.append(p)
    return missing


def sidecar_dict(item: QueueItem) -> dict:
    return {
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


def write_pending_sidecar(item: QueueItem, output_dir: Path) -> None:
    sidecar_path = output_dir / f"{item.archive_name}.pending.json"
    sidecar_path.write_text(json.dumps(sidecar_dict(item), indent=2), encoding="utf-8")
    log.info("Wrote pending sidecar: %s", sidecar_path)


async def _pack_entry(
    entry: WatchEntry, conf: dict, platforms: list[str] | None = None
) -> tuple[bool, list[QueueItem]]:
    output_dir = Path(entry.output_dir or conf["output_dir"])
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
            output_dir=entry.output_dir,
        )
        for p in (platforms if platforms is not None else entry.platforms)
    ]

    all_ok = True
    pending: list[QueueItem] = []
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
            write_pending_sidecar(item, output_dir)
            pending.append(item)
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

    return all_ok, pending


async def _check_all(entries: list[WatchEntry], conf: dict) -> tuple[bool, list[QueueItem]]:
    any_failed = False
    pending: list[QueueItem] = []

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
            ok, entry_pending = await _pack_entry(entry, conf)
            pending.extend(entry_pending)
            if ok:
                entry.last_build_id = new_build_id
            else:
                any_failed = True
        else:
            missing = _missing_platforms(entry, new_build_id, conf)
            if missing:
                log.info("Filling missing platforms for %s: %s", entry.name, missing)
                ok, entry_pending = await _pack_entry(entry, conf, platforms=missing)
                pending.extend(entry_pending)
                if not ok:
                    any_failed = True
            else:
                log.info("No change for %s: still at build %s", entry.name, new_build_id)

        entry.last_checked = datetime.now(tz=UTC).isoformat()
        save_watchlist(entries)
        await asyncio.sleep(2)

    return not any_failed, pending


def _notify_pending(items: list[QueueItem], conf: dict) -> None:
    """Send a desktop notification for downloads left unprocessed by a daemon run."""
    if not conf.get("notify_on_pending", True):
        return
    notify_send = shutil.which("notify-send")
    if not notify_send:
        log.info("notify-send not found; skipping desktop notification")
        return

    names = sorted({item.game_name or f"App {item.appid}" for item in items})
    builds = sorted({item.build_id for item in items if item.build_id})
    summary = _("New downloads ready to process")
    body = ", ".join(names)
    if builds:
        body = f"{body} ({_('Builds')}: {', '.join(builds)})"

    try:
        subprocess.run(
            [
                notify_send,
                "--app-name=GnuSteamPacker",
                "--category=transfer.complete",
                summary,
                body,
            ],
            timeout=10,
        )
        log.info("Sent notification for %d pending download(s).", len(items))
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Failed to send notification: %s", exc)


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


async def check_new_builds(entries: list[WatchEntry], conf: dict) -> list[QueueItem]:
    """Query Steam API for build ID changes; return QueueItems for new builds (GUI path).

    Updates last_checked and handles first-run recording. Does NOT download - the caller
    (window.py) adds returned items to the queue so progress is visible in the Queue tab.
    last_build_id is updated by window.py after successful download.
    """
    new_items: list[QueueItem] = []

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
            log.info("First check for %s: recorded build %s.", entry.name, new_build_id)
            entry.last_build_id = new_build_id
        elif new_build_id != entry.last_build_id:
            log.info("New build for %s: %s → %s", entry.name, entry.last_build_id, new_build_id)
            for platform in entry.platforms:
                new_items.append(
                    QueueItem(
                        appid=entry.appid,
                        game_name=entry.name,
                        platform=platform,
                        branch=entry.branch,
                        branch_password=entry.branch_password,
                        from_daemon=True,
                        output_dir=entry.output_dir,
                    )
                )
        else:
            missing = _missing_platforms(entry, new_build_id, conf)
            if missing:
                log.info("Filling missing platforms for %s: %s", entry.name, missing)
                for platform in missing:
                    new_items.append(
                        QueueItem(
                            appid=entry.appid,
                            game_name=entry.name,
                            platform=platform,
                            branch=entry.branch,
                            branch_password=entry.branch_password,
                            from_daemon=True,
                            output_dir=entry.output_dir,
                        )
                    )
            else:
                log.info("No change for %s: still at build %s", entry.name, new_build_id)

        entry.last_checked = datetime.now(tz=UTC).isoformat()
        save_watchlist(entries)
        await asyncio.sleep(2)

    return new_items


async def check_all() -> list[QueueItem]:
    """Public async entry for GUI 'Run now': returns QueueItems for new builds."""
    conf = cfg.load()
    entries = load_watchlist()
    if not entries:
        return []
    return await check_new_builds(entries, conf)


def run_daemon_check() -> int:
    conf = cfg.load()
    _setup_logging(conf)
    entries = load_watchlist()

    if not entries:
        log.info("Watchlist is empty, nothing to check.")
        return 0

    enabled = [e for e in entries if e.enabled]
    log.info("Daemon check: %d/%d entries enabled.", len(enabled), len(entries))

    ok, pending = asyncio.run(_check_all(entries, conf))
    if pending:
        _notify_pending(pending, conf)
    return 0 if ok else 1
