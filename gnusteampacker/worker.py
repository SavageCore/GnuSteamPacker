"""Async download pipeline: info fetch → download → vdf_clean → manifests → compress."""

import logging
import re
import shutil
import time
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
from gnusteampacker.queue_model import QueueItem, Status

log = logging.getLogger(__name__)

UpdateCB = Callable[[QueueItem], None]

_MANIFEST_RE = re.compile(r"^(\d+)_(\d+)\.manifest$")


def _write_acf(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)


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


def _manifest_metrics(depot_data: dict, manifest_id: str) -> tuple[str, str]:
    manifests = depot_data.get("manifests", {})
    for branch_data in manifests.values():
        if isinstance(branch_data, dict) and str(branch_data.get("gid", "")) == str(manifest_id):
            return str(branch_data.get("size", "")), str(branch_data.get("download", ""))
    return "", ""


def _write_appmanifests(
    install_dir: Path,
    item: QueueItem,
    game_info: dict,
    manifest_overrides: dict[str, str] | None = None,
    shared_info: dict | None = None,
) -> None:
    steamapps_dir = install_dir / "steamapps"
    steamapps_dir.mkdir(parents=True, exist_ok=True)
    appmanifest = steamapps_dir / f"appmanifest_{item.appid}.acf"
    installed_depots: list[tuple[str, str, str, str, str | None]] = []
    shared_depots: list[tuple[str, str]] = []
    depots = game_info.get("depots", {})
    depot_iter = (
        [(depot_id, depots.get(depot_id, {})) for depot_id in manifest_overrides]
        if manifest_overrides
        else list(depots.items())
    )
    for depot_id, depot_data in depot_iter:
        if not depot_id.isdigit():
            continue
        if manifest_overrides and depot_id not in manifest_overrides:
            continue
        manifests = depot_data.get("manifests", {})
        if manifest_overrides:
            manifest_id = manifest_overrides.get(depot_id, "")
        else:
            branch_manifest = manifests.get(item.branch) or manifests.get("public") or {}
            if isinstance(branch_manifest, dict):
                manifest_id = str(branch_manifest.get("gid", ""))
            else:
                manifest_id = str(branch_manifest)
        if manifest_id and not depot_data.get("depotfromapp"):
            size, download = _manifest_metrics(depot_data, manifest_id)
            size = size or str(depot_data.get("size", ""))
            download = download or size
            installed_depots.append(
                (
                    depot_id,
                    manifest_id,
                    size,
                    download,
                    depot_data.get("dlcappid"),
                )
            )
        if depot_data.get("depotfromapp") == "228980" and depot_data.get("sharedinstall") == "1":
            shared_depots.append((depot_id, manifest_id))

    build_id = item.build_id or game_info.get(f"build_{item.branch}", "")
    game_size = sum(int(size) for _, _, size, _, _ in installed_depots if str(size).isdigit())
    game_download = sum(
        int(download) for _, _, _, download, _ in installed_depots if str(download).isdigit()
    )
    has_dlc = any(bool(dlcappid) for *_, dlcappid in installed_depots)
    download_type = "2" if has_dlc or shared_depots else "1"

    main_data = {
        "AppState": {
            "appid": item.appid,
            "Universe": "1",
            "LauncherPath": "0",
            "name": game_info.get("name", item.game_name),
            "StateFlags": "4",
            "installdir": game_info.get("installdir", item.game_name),
            "LastUpdated": str(int(time.time())),
            "LastPlayed": "0",
            "SizeOnDisk": str(game_size),
            "StagingSize": "0",
            "buildid": build_id,
            "LastOwner": "0",
            "DownloadType": download_type,
            "UpdateResult": "0",
            "BytesToDownload": str(game_download),
            "BytesDownloaded": str(game_download),
            "BytesToStage": str(game_size),
            "BytesStaged": str(game_size),
            "TargetBuildID": build_id if download_type == "1" else "0",
            "AutoUpdateBehavior": "0",
            "AllowOtherDownloadsWhileRunning": "0",
            "ScheduledAutoUpdate": "0",
        }
    }
    if installed_depots:
        main_data["AppState"]["InstalledDepots"] = {
            depot_id: {
                "manifest": manifest_id,
                "size": size,
                **({"dlcappid": dlcappid} if dlcappid else {}),
            }
            for depot_id, manifest_id, size, _, dlcappid in installed_depots
        }
    if shared_depots:
        main_data["AppState"]["SharedDepots"] = {
            depot_id: "228980" for depot_id, _ in shared_depots
        }
    main_data["AppState"]["UserConfig"] = {}
    main_data["AppState"]["MountedConfig"] = {}
    _write_acf(appmanifest, main_data)

    has_shared_redist = (install_dir / "_CommonRedist").exists() or (
        install_dir / "steamapps" / "common" / "Steamworks Shared" / "_CommonRedist"
    ).exists()
    if shared_info is not None and has_shared_redist:
        shared_manifest = steamapps_dir / "appmanifest_228980.acf"
        shared_depot = None
        for depot_id, depot_data in shared_info.get("depots", {}).items():
            if depot_id.isdigit() and (
                depot_data.get("sharedinstall") == "1" or depot_id == "228989"
            ):
                manifests = depot_data.get("manifests", {})
                public_manifest = manifests.get("public") or {}
                if isinstance(public_manifest, dict):
                    manifest_id = str(public_manifest.get("gid", ""))
                else:
                    manifest_id = str(public_manifest)
                if manifest_id:
                    size, _ = _manifest_metrics(depot_data, manifest_id)
                    shared_depot = (depot_id, manifest_id, size)
                    break
        shared_size = int(shared_depot[2]) if shared_depot and str(shared_depot[2]).isdigit() else 0
        shared_data = {
            "AppState": {
                "appid": "228980",
                "Universe": "1",
                "LauncherPath": "0",
                "name": shared_info.get("name", "Steamworks Common Redistributables"),
                "StateFlags": "4",
                "installdir": "Steamworks Shared",
                "LastUpdated": str(int(time.time()) - 1),
                "LastPlayed": "0",
                "SizeOnDisk": str(shared_size),
                "StagingSize": "0",
                "buildid": shared_info.get("build_public", ""),
                "LastOwner": "0",
                "DownloadType": "0",
                "AutoUpdateBehavior": "0",
                "AllowOtherDownloadsWhileRunning": "0",
                "ScheduledAutoUpdate": "0",
            }
        }
        if shared_depot:
            shared_data["AppState"]["InstalledDepots"] = {
                shared_depot[0]: {"manifest": shared_depot[1], "size": shared_depot[2]}
            }
        install_script = install_dir / "_CommonRedist" / "vcredist" / "2022" / "installscript.vdf"
        if not install_script.exists():
            install_script = (
                install_dir
                / "steamapps"
                / "common"
                / "Steamworks Shared"
                / "_CommonRedist"
                / "vcredist"
                / "2022"
                / "installscript.vdf"
            )
        if install_script.exists():
            shared_data["AppState"]["InstallScripts"] = {
                "228989": "_CommonRedist\\vcredist\\2022\\installscript.vdf"
            }
        shared_data["AppState"]["UserConfig"] = {}
        shared_data["AppState"]["MountedConfig"] = {}
        _write_acf(shared_manifest, shared_data)


def _write_missing_shared_manifest(
    install_dir: Path,
    shared_info: dict | None,
    shared_depot_ids: set[str],
    manifest_overrides: dict[str, str],
) -> None:
    if not shared_info or not shared_depot_ids:
        return
    steamapps_dir = install_dir / "steamapps"
    shared_manifest = steamapps_dir / "appmanifest_228980.acf"
    if shared_manifest.exists():
        return

    shared_depot = None
    depots = shared_info.get("depots", {})
    for depot_id in sorted(shared_depot_ids):
        depot_data = depots.get(depot_id, {})
        if not isinstance(depot_data, dict):
            continue
        manifest_id = manifest_overrides.get(depot_id, "")
        if not manifest_id:
            manifests = depot_data.get("manifests", {})
            public_manifest = manifests.get("public") or {}
            if isinstance(public_manifest, dict):
                manifest_id = str(public_manifest.get("gid", ""))
            else:
                manifest_id = str(public_manifest)
        if not manifest_id:
            continue
        size, _ = _manifest_metrics(depot_data, manifest_id)
        shared_depot = (depot_id, manifest_id, size)
        break

    if not shared_depot:
        return

    shared_size = int(shared_depot[2]) if str(shared_depot[2]).isdigit() else 0
    shared_data = {
        "AppState": {
            "appid": "228980",
            "Universe": "1",
            "LauncherPath": "0",
            "name": shared_info.get("name", "Steamworks Common Redistributables"),
            "StateFlags": "4",
            "installdir": "Steamworks Shared",
            "LastUpdated": str(int(time.time()) - 1),
            "LastPlayed": "0",
            "SizeOnDisk": str(shared_size),
            "StagingSize": "0",
            "buildid": shared_info.get("build_public", ""),
            "LastOwner": "0",
            "DownloadType": "0",
            "AutoUpdateBehavior": "0",
            "AllowOtherDownloadsWhileRunning": "0",
            "ScheduledAutoUpdate": "0",
        }
    }
    shared_data["AppState"]["InstalledDepots"] = {
        shared_depot[0]: {"manifest": shared_depot[1], "size": shared_depot[2]}
    }
    install_script = (
        install_dir
        / "steamapps"
        / "common"
        / "Steamworks Shared"
        / "_CommonRedist"
        / "vcredist"
        / "2022"
        / "installscript.vdf"
    )
    if install_script.exists():
        shared_data["AppState"]["InstallScripts"] = {
            "228989": "_CommonRedist\\vcredist\\2022\\installscript.vdf"
        }
    shared_data["AppState"]["UserConfig"] = {}
    shared_data["AppState"]["MountedConfig"] = {}
    _write_acf(shared_manifest, shared_data)


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
    shared_depot_ids: set[str] = set()

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

    # ── 2. Fetch game info and initial depot list ──────────────────────────
    push(Status.GETINFO)
    try:
        depot_names = await steam_api.fetch_depot_names()
        game_info = await steam_api.get_game_info(item.appid)
        item.game_name = game_info["name"]
        item.build_id = game_info.get(f"build_{item.branch}") or game_info.get("build_public", "")
        item.build_time = game_info.get(f"time_{item.branch}") or game_info.get("time_public", "")
        item.depot_list = release_text.build_depot_list(game_info, depot_names, item.branch)
        shared_info = None
    except Exception as e:
        push(Status.FAIL, detail=f"Info fetch failed: {e}")
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
            detail=(
                "SteamCMD output missing appmanifest for app "
                f"{item.appid} in: {', '.join(str(p) for p in steam_roots)}"
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
            )
            volatile_ui_file = steamapps_dest / "common" / installdir / "imgui.ini"
            volatile_ui_file.unlink(missing_ok=True)

    for shared_appid in sorted(shared_source_appids):
        shared_acf_src = steamapps_src / f"appmanifest_{shared_appid}.acf"
        if not shared_acf_src.exists():
            continue
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
                shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)

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
            detail=f"No files found under {steam_common}",
        )
        return

    # ── 4. Prepare shared app info (for Steamworks Shared if present) ─────
    push(Status.CLEANING, 0.0)
    if (install_dir / "_CommonRedist").exists() or (
        install_dir / "steamapps" / "common" / "Steamworks Shared" / "_CommonRedist"
    ).exists():
        try:
            shared_info = await steam_api.get_game_info("228980")
        except Exception:
            shared_info = None

    # ── 5. Rebuild depot list with real manifest GIDs ──────────────────────
    # Use manifests generated by the SteamCMD primary download pass.
    manifest_overrides: dict[str, str] = {}
    selected_manifest_files: set[str] = set()
    depotcache_dir = install_dir / "depotcache"
    if depotcache_dir.exists():
        for f in depotcache_dir.glob("*.manifest"):
            m = _MANIFEST_RE.match(f.name)
            if not m:
                continue
            manifest_overrides[m.group(1)] = m.group(2)
            selected_manifest_files.add(f.name)

    _write_missing_shared_manifest(
        install_dir,
        shared_info,
        shared_depot_ids,
        manifest_overrides,
    )

    # ── 7. Finalize metadata and reorganise layout ─────────────────────────
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
