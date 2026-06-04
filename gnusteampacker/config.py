import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gnusteampacker"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "gnusteampacker"

CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "steamcmd_path": str(DATA_DIR / "steamcmd" / "steamcmd.sh"),
    "steamcmd_auto_download": True,
    "output_dir": str(Path.home() / "GnuSteamPacker"),
    "split_size_mb": 5120,
    "color_scheme": "default",  # "default" | "light" | "dark"
}


def load() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        with CONFIG_FILE.open() as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with CONFIG_FILE.open("w") as f:
        json.dump(cfg, f, indent=2)
