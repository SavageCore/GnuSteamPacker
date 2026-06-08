#!/usr/bin/env python3
"""Clear SteamCMD cached authentication data."""

from __future__ import annotations

from pathlib import Path

from gnusteampacker import config as cfg
from gnusteampacker import steamcmd


def clear_steamcmd_auth_cache() -> None:
    conf = cfg.load()
    steamcmd_path = Path(conf["steamcmd_path"])
    steamcmd.clear_cached_login(steamcmd_path)


def main() -> int:
    clear_steamcmd_auth_cache()
    print("Cleared SteamCMD cached login data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
