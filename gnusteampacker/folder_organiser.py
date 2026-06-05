"""Organise SteamCMD output into the expected archive layout."""

import re
import shutil
from pathlib import Path

import vdf

# Matches data rows in DepotDownloader manifest .txt files:
#   "  <size>  <chunks>  <sha40hex>  <flags>  path/to/entry"
_MANIFEST_LINE_RE = re.compile(r"^\s+\d+\s+\d+\s+[0-9a-f]{40}\s+\d+\s+(.+)$")
_MANIFEST_TXT_RE = re.compile(r"^manifest_(\d+)_\d+\.txt$")
_ROOT_SKIP = {"steamapps", ".DepotDownloader", "depotcache"}


def reorganise(install_dir: Path, appid: str | int) -> None:
    """Reorganise SteamCMD output into the SSP-compatible archive layout.

    SteamCMD places all game content (main depot + shared depots) flat at
    install_dir/. The manifest .txt files written by DepotDownloader tell us
    which root-level entries belong to which installdir so we can split them
    correctly (e.g. _CommonRedist → Steamworks Shared).
    """
    depot_map = _build_depot_map(install_dir, appid)
    main_installdir = _find_installdir(install_dir, appid)

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
        installdir = root_to_installdir.get(entry.name) or main_installdir
        if installdir:
            dest = install_dir / "steamapps" / "common" / installdir
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(entry), str(dest / entry.name))

    # Delete manifest .txt files — they are DepotDownloader debug exports,
    # not part of the Steam game content.
    for txt in install_dir.glob("manifest_*.txt"):
        txt.unlink(missing_ok=True)

    # Promote .DepotDownloader/*.manifest → depotcache/.
    dd_cache = install_dir / ".DepotDownloader"
    if dd_cache.exists():
        depotcache = install_dir / "depotcache"
        depotcache.mkdir(exist_ok=True)
        for f in dd_cache.glob("*.manifest"):
            shutil.move(str(f), str(depotcache / f.name))
        shutil.rmtree(dd_cache, ignore_errors=True)


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
    """Extract unique top-level names from a DepotDownloader manifest .txt file."""
    roots: set[str] = set()
    for line in txt_path.read_text(errors="replace").splitlines():
        m = _MANIFEST_LINE_RE.match(line)
        if m:
            root = m.group(1).split("/")[0].split("\\")[0]
            if root:
                roots.add(root)
    return roots
