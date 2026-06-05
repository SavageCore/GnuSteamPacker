"""Clean sensitive data from DepotDownloader-generated ACF files."""

import shutil
from pathlib import Path

import vdf

KEYS_TO_ZERO = {"LastOwner", "LauncherPath", "UserID", "AccountID"}


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


def clean_steamapps(steamapps_dir: Path) -> None:
    """Clean all ACF files and remove non-essential directories."""
    for acf in steamapps_dir.glob("*.acf"):
        try:
            clean_acf(acf)
        except Exception:
            pass

    for subdir in ("workshop", "downloading", "temp"):
        p = steamapps_dir / subdir
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    for name in ("libraryfolders.vdf",):
        p = steamapps_dir / name
        if p.exists():
            p.unlink(missing_ok=True)
