"""Clean sensitive data from generated ACF files."""

import logging
import shutil
from pathlib import Path

import vdf

log = logging.getLogger(__name__)

KEYS_TO_ZERO = {"LastOwner", "LauncherPath"}


def clean_acf(path: Path) -> None:
    """Zero out privacy-sensitive keys in an ACF manifest file."""
    with path.open(encoding="utf-8", errors="replace") as f:
        data = vdf.load(f)
    _zero_keys(data)
    with path.open("w", encoding="utf-8") as f:
        vdf.dump(data, f, pretty=True)


def _zero_keys(obj: object) -> None:
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            if k in KEYS_TO_ZERO:
                obj[k] = "0"
            else:
                _zero_keys(obj[k])
        if "AppState" in obj and isinstance(obj["AppState"], dict):
            for key in KEYS_TO_ZERO:
                obj["AppState"].setdefault(key, "0")


def clean_steamapps(steamapps_dir: Path) -> None:
    """Clean all ACF files and remove non-essential directories."""
    for acf in steamapps_dir.glob("*.acf"):
        try:
            clean_acf(acf)
        except Exception as e:
            log.warning("failed to clean %s: %s", acf, e)

    for subdir in ("workshop", "downloading", "temp"):
        p = steamapps_dir / subdir
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    for name in ("libraryfolders.vdf",):
        p = steamapps_dir / name
        if p.exists():
            p.unlink(missing_ok=True)
