import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gnusteampacker"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "gnusteampacker"

CONFIG_FILE = CONFIG_DIR / "config.json"
WATCHLIST_FILE = CONFIG_DIR / "watchlist.json"

_cpu = os.cpu_count() or 4

DEFAULTS = {
    "steamcmd_path": str(DATA_DIR / "steamcmd" / "steamcmd.sh"),
    "steamcmd_auto_download": True,
    "output_dir": str(Path.home() / "GnuSteamPacker"),
    "color_scheme": "default",  # "default" | "light" | "dark"
    "language": "system",  # "system" | language code, e.g. "en", "ru"
    "compression_level": 5,
    "compression_threads": max(1, _cpu // 2),
    "window_width": 1000,
    "window_height": 800,
    "window_maximized": False,
    "remember_login": True,
    "notify_on_pending": True,
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


def forum_post_cache_path(appid: str) -> Path:
    return DATA_DIR / "forum_posts" / f"{appid}.txt"


def save_forum_post_cache(appid: str, content: str) -> None:
    path = forum_post_cache_path(appid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
