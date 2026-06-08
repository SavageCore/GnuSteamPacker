"""Async download pipeline: info fetch → download → vdf_clean → manifests → compress."""

import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import vdf

from gnusteampacker import (
    compressor,
    credentials,
    folder_organiser,
    release_text,
    steam_api,
    steamcmd,
    vdf_cleaner,
)
from gnusteampacker import config as cfg
from gnusteampacker.i18n import _
from gnusteampacker.queue_model import QueueItem, Status

log = logging.getLogger(__name__)

UpdateCB = Callable[[QueueItem], None]

_MANIFEST_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")


def _ignore_dangling_symlinks(src: str, names: list[str]) -> set[str]:
    """Skip dangling symlinks — valid ones (e.g. .so soname aliases) are preserved."""
    return {n for n in names if (p := Path(src, n)).is_symlink() and not p.exists()}


def _depot_list_from_acfs(steamapps_dir: Path, depot_names: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for acf in sorted(steamapps_dir.glob("appmanifest_*.acf")):
        with acf.open(encoding="utf-8", errors="replace") as f:
            app_state = vdf.load(f).get("AppState", {})
        installed = app_state.get("InstalledDepots", {})
        if not isinstance(installed, dict):
            continue
        for depot_id, depot in installed.items():
            manifest = ""
            if isinstance(depot, dict):
                manifest = str(depot.get("manifest", ""))
            depot_name = depot_names.get(str(depot_id), "")
            label = f"{depot_id} - {depot_name}" if depot_name else f"{depot_id} - DepotName"
            lines.append(f"{label} [Manifest {manifest}]")
    return lines


async def process_item(
    item: QueueItem,
    update_cb: UpdateCB,
    steam_guard_code: str | None = None,
    auth_override: dict | None = None,
) -> None:
    conf = cfg.load()
    sc_path = Path(conf["steamcmd_path"])
    output_base = Path(conf["output_dir"])
    compression_level = int(conf.get("compression_level", 5))
    compression_threads = int(conf.get("compression_threads", 1))
    username = (auth_override or {}).get("username", credentials.get_username()).strip()
    stored_password = credentials.get_password()
    password = (auth_override or {}).get("password", stored_password)
    remember_login = bool(
        (auth_override or {}).get("remember_login", conf.get("remember_login", True))
    )

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
            push(Status.FAIL, detail=_("SteamCMD install failed: {error}").format(error=e))
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
        push(Status.FAIL, detail=_("Info fetch failed: {error}").format(error=e))
        return

    # ── 3. Download via SteamCMD ───────────────────────────────────────────
    push(Status.DOWNLOADING, 0.0)
    install_dir = output_base / item.archive_name
    shutil.rmtree(install_dir, ignore_errors=True)
    (output_base / f"{item.archive_name}.7z").unlink(missing_ok=True)
    (output_base / f"{item.archive_name}.txt").unlink(missing_ok=True)

    def sc_progress(pct: float, line: str) -> None:
        low = line.lower()
        if "logging in" in low or "steam guard" in low:
            push(Status.AUTHENTICATING)
            return
        push(Status.DOWNLOADING, pct)

    prefer_cached_login = steam_guard_code is None and bool(username)
    steamcmd_password = "" if prefer_cached_login else password

    try:
        ok, reason = await steamcmd.run_download(
            item,
            sc_path,
            username,
            steamcmd_password,
            install_dir,
            sc_progress,
            remember_login=remember_login,
            steam_guard_code=steam_guard_code,
        )
    except Exception as e:
        push(Status.FAIL, detail=str(e))
        return
    if not ok and reason == "badlogin" and prefer_cached_login:
        try:
            ok, reason = await steamcmd.run_download(
                item,
                sc_path,
                username,
                stored_password,
                install_dir,
                sc_progress,
                remember_login=remember_login,
                steam_guard_code=steam_guard_code,
            )
        except Exception as e:
            push(Status.FAIL, detail=str(e))
            return

    if not ok:
        if reason == "badlogin" and remember_login:
            steamcmd.clear_cached_login(sc_path)
            credentials.clear_password()
        status_map = {
            "nosub": Status.NOSUB,
            "ratelimited": Status.RATELIMITED,
            "badlogin": Status.BADLOGIN,
            "steamguard": Status.STEAMGUARD,
        }
        push(status_map.get(reason, Status.FAIL), detail=reason)
        return

    try:
        steam_roots = [
            sc_path.parent,
            sc_path.parent / ".home" / "Steam",
        ]
        manifest_name = f"appmanifest_{item.appid}.acf"
        steam_root = next(
            (root for root in steam_roots if (root / "steamapps" / manifest_name).exists()),
            None,
        )
        if steam_root is None:
            push(
                Status.FAIL,
                detail=_("SteamCMD output missing appmanifest for app {appid} in: {paths}").format(
                    appid=item.appid, paths=", ".join(str(p) for p in steam_roots)
                ),
            )
            return
        steamapps_src = steam_root / "steamapps"
        depotcache_src = steam_root / "depotcache"
        install_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(install_dir / "steamapps", ignore_errors=True)
        shutil.rmtree(install_dir / "depotcache", ignore_errors=True)
        steamapps_dest = install_dir / "steamapps"
        depotcache_dest = install_dir / "depotcache"
        steamapps_dest.mkdir(parents=True, exist_ok=True)
        (steamapps_dest / "common").mkdir(parents=True, exist_ok=True)

        main_acf_src = steamapps_src / f"appmanifest_{item.appid}.acf"
        shutil.copy2(main_acf_src, steamapps_dest / main_acf_src.name)
        with main_acf_src.open(encoding="utf-8", errors="replace") as f:
            main_state = vdf.load(f).get("AppState", {})

        shared_source_appids = {
            str(appid)
            for appid in (main_state.get("SharedDepots", {}) or {}).values()
            if str(appid).isdigit()
        }
        shared_depot_ids = {
            str(depot_id)
            for depot_id in (main_state.get("SharedDepots", {}) or {}).keys()
            if str(depot_id).isdigit()
        }
        relevant_ids = {str(item.appid)}
        relevant_ids.update(
            str(depot_id) for depot_id in (main_state.get("InstalledDepots", {}) or {}).keys()
        )
        relevant_ids.update(shared_depot_ids)

        installdir = str(main_state.get("installdir", "")).strip()
        if installdir:
            src_common = steamapps_src / "common" / installdir
            if src_common.exists():
                shutil.copytree(
                    src_common,
                    steamapps_dest / "common" / installdir,
                    dirs_exist_ok=True,
                    symlinks=True,
                    ignore=_ignore_dangling_symlinks,
                )
                volatile_ui_file = steamapps_dest / "common" / installdir / "imgui.ini"
                volatile_ui_file.unlink(missing_ok=True)

        for shared_appid in sorted(shared_source_appids):
            shared_acf_src = steamapps_src / f"appmanifest_{shared_appid}.acf"
            if not shared_acf_src.exists():
                continue
            shutil.copy2(shared_acf_src, steamapps_dest / shared_acf_src.name)
            with shared_acf_src.open(encoding="utf-8", errors="replace") as f:
                shared_state = vdf.load(f).get("AppState", {})
            shared_installdir = str(shared_state.get("installdir", "")).strip()
            if not shared_installdir:
                continue
            src_shared = steamapps_src / "common" / shared_installdir
            if not src_shared.exists():
                continue
            install_scripts = shared_state.get("InstallScripts", {}) or {}
            for depot_id in sorted(shared_depot_ids):
                script_path = str(install_scripts.get(depot_id, "")).replace("\\", "/").strip("/")
                if not script_path:
                    continue
                rel_dir = Path(script_path).parent
                src_dir = src_shared / rel_dir
                dest_dir = steamapps_dest / "common" / shared_installdir / rel_dir
                if src_dir.exists() and src_dir.is_dir():
                    shutil.copytree(
                        src_dir,
                        dest_dir,
                        dirs_exist_ok=True,
                        symlinks=True,
                        ignore=_ignore_dangling_symlinks,
                    )

        if depotcache_src.exists():
            depotcache_dest.mkdir(parents=True, exist_ok=True)
            for manifest in depotcache_src.glob("*.manifest"):
                m = _MANIFEST_RE.match(manifest.name)
                if not m:
                    continue
                if m.group(1) not in relevant_ids:
                    continue
                shutil.copy2(manifest, depotcache_dest / manifest.name)

        # Guard: game files should exist after download handoff.
        steam_common = install_dir / "steamapps" / "common"
        has_game_files = steam_common.exists() and any(p.is_file() for p in steam_common.rglob("*"))
        if not has_game_files:
            push(
                Status.FAIL,
                detail=_("No files found under {path}").format(path=steam_common),
            )
            return

        push(Status.CLEANING, 0.0)
        selected_manifest_files: set[str] = set()
        depotcache_dir = install_dir / "depotcache"
        if depotcache_dir.exists():
            for f in depotcache_dir.glob("*.manifest"):
                m = _MANIFEST_RE.match(f.name)
                if not m:
                    continue
                selected_manifest_files.add(f.name)

        # ── 7. Finalize metadata and reorganise layout ─────────────────────
        push(Status.CLEANING, 1.0)
        steamapps_dir = install_dir / "steamapps"
        if steamapps_dir.exists():
            try:
                vdf_cleaner.clean_steamapps(steamapps_dir)
            except Exception as e:
                log.warning("vdf_cleaner failed: %s", e)
            try:
                item.depot_list = _depot_list_from_acfs(steamapps_dir, depot_names)
            except Exception as e:
                log.warning("depot list build from acf failed: %s", e)
        folder_organiser.reorganise(
            install_dir,
            item.appid,
            main_installdir=game_info.get("installdir", item.game_name),
            selected_manifest_files=selected_manifest_files or None,
        )
    except Exception as exc:
        log.exception("Failed to reorganise downloaded files for %s", item.archive_name)
        push(
            Status.FAIL,
            detail=_("Failed to organise downloaded files: {error}").format(error=exc),
        )
        return

    # ── 8. Compress ────────────────────────────────────────────────────────
    push(Status.COMPRESSING, 0.0)
    try:
        await compressor.compress(
            source_dir=install_dir,
            archive_name=item.archive_name,
            output_dir=output_base,
            progress_cb=lambda line: push(Status.COMPRESSING, item.progress),
            level=compression_level,
            threads=compression_threads,
        )
    except Exception as e:
        push(Status.FAIL, detail=str(e))
        return

    # ── 9. Write BBCode release text ───────────────────────────────────────
    txt_path = output_base / (item.archive_name + ".txt")
    txt_path.write_text(release_text.generate(item), encoding="utf-8")

    push(Status.COMPLETE, 1.0)
