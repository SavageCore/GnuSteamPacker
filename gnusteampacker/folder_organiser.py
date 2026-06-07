"""Organise downloader output into the expected Steam library layout."""

import re
import shutil
from pathlib import Path

import vdf

# Matches data rows in manifest .txt files:
#   "  <size>  <chunks>  <sha40hex>  <flags>  path/to/entry"
_MANIFEST_LINE_RE = re.compile(r"^\s+\d+\s+\d+\s+[0-9a-f]{40}\s+\d+\s+(.+)$")
_MANIFEST_TXT_RE = re.compile(r"^manifest_(\d+)_\d+\.txt$")
_ROOT_SKIP = {"steamapps", "depotcache"}
_SHARED_ROOT = "Steamworks Shared"


def reorganise(
    install_dir: Path,
    appid: str | int,
    main_installdir: str | None = None,
    shared_installdir: str = _SHARED_ROOT,
    selected_manifest_files: set[str] | None = None,
) -> None:
    """Move payload files under steamapps/common and keep shared redistributables separate."""
    depot_map = _build_depot_map(install_dir, appid)
    main_installdir = main_installdir or _find_installdir(install_dir, appid)

    # Build root-entry → installdir mapping from manifest .txt files.
    root_to_installdir: dict[str, str] = {}
    for txt in install_dir.glob("manifest_*.txt"):
        m = _MANIFEST_TXT_RE.match(txt.name)
        if not m:
            continue
        installdir = depot_map.get(m.group(1)) or main_installdir
        if not installdir:
            continue
        for root_entry in _parse_root_entries(txt):
            root_to_installdir[root_entry] = installdir

    # Move game content from root to steamapps/common/<installdir>/.
    for entry in list(install_dir.iterdir()):
        if entry.name in _ROOT_SKIP or _MANIFEST_TXT_RE.match(entry.name):
            continue
        if entry.name == "_CommonRedist":
            dest = install_dir / "steamapps" / "common" / shared_installdir
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest / entry.name))
            continue
        installdir = root_to_installdir.get(entry.name) or main_installdir
        if installdir:
            dest = install_dir / "steamapps" / "common" / installdir
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest / entry.name))

    # Delete manifest .txt files — they are metadata exports,
    # not part of the Steam game content.
    for txt in install_dir.glob("manifest_*.txt"):
        txt.unlink(missing_ok=True)

    _fix_known_case_mismatches(install_dir, main_installdir)


def _build_depot_map(install_dir: Path, appid: str | int) -> dict[str, str]:
    """Return {depot_id_str: installdir} by reading all relevant ACF files."""
    steamapps = install_dir / "steamapps"
    result: dict[str, str] = {}

    main_acf = steamapps / f"appmanifest_{appid}.acf"
    if not main_acf.exists():
        return result
    try:
        with main_acf.open(errors="replace") as f:
            main = vdf.load(f).get("AppState", {})
    except Exception:
        return result

    main_installdir = main.get("installdir", "")
    for depot_id in main.get("InstalledDepots", {}):
        result[str(depot_id)] = main_installdir

    for depot_id, source_appid in main.get("SharedDepots", {}).items():
        shared_acf = steamapps / f"appmanifest_{source_appid}.acf"
        if not shared_acf.exists():
            continue
        try:
            with shared_acf.open(errors="replace") as f:
                shared = vdf.load(f).get("AppState", {})
            if shared_installdir := shared.get("installdir", ""):
                result[str(depot_id)] = shared_installdir
        except Exception:
            pass

    return result


def _find_installdir(install_dir: Path, appid: str | int) -> str | None:
    acf = install_dir / "steamapps" / f"appmanifest_{appid}.acf"
    if not acf.exists():
        return None
    try:
        with acf.open(errors="replace") as f:
            return vdf.load(f).get("AppState", {}).get("installdir") or None
    except Exception:
        return None


def _parse_root_entries(txt_path: Path) -> set[str]:
    """Extract unique top-level names from a manifest .txt file."""
    roots: set[str] = set()
    for line in txt_path.read_text(errors="replace").splitlines():
        m = _MANIFEST_LINE_RE.match(line)
        if m:
            root = m.group(1).split("/")[0].split("\\")[0]
            if root:
                roots.add(root)
    return roots


def _fix_known_case_mismatches(install_dir: Path, main_installdir: str | None) -> None:
    if not main_installdir:
        return
    game_root = install_dir / "steamapps" / "common" / main_installdir
    lower_openal = game_root / "openal32.dll"
    upper_openal = game_root / "OpenAL32.dll"
    if lower_openal.exists() and upper_openal.exists():
        lower_openal.unlink(missing_ok=True)
    elif lower_openal.exists() and not upper_openal.exists():
        lower_openal.rename(upper_openal)
