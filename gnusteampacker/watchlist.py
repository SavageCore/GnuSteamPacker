"""Persistent watchlist for automatic Steam build monitoring."""

import dataclasses
import json
from dataclasses import dataclass, field

from gnusteampacker.config import CONFIG_DIR

WATCHLIST_FILE = CONFIG_DIR / "watchlist.json"


@dataclass
class WatchEntry:
    appid: str
    name: str
    platforms: list[str]
    branch: str
    branch_password: str
    last_build_id: str  # "" = never checked
    last_checked: str  # ISO-8601 or ""
    enabled: bool = field(default=True)


def load() -> list[WatchEntry]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        with WATCHLIST_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        return [WatchEntry(**e) for e in data]
    except (json.JSONDecodeError, OSError, TypeError, KeyError):
        return []


def save(entries: list[WatchEntry]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with WATCHLIST_FILE.open("w", encoding="utf-8") as f:
        json.dump([dataclasses.asdict(e) for e in entries], f, indent=2)
