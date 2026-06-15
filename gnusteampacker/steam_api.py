"""Steam public API helpers - no API key required."""

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

# Steam autocomplete suggest - returns HTML, no auth required
STORE_SUGGEST = (
    "https://store.steampowered.com/search/suggest"
    "?term={term}&f=games&cc=US&l=english"
    "&use_store_query=1&use_search_spellcheck=1"
)
STEAMCMD_INFO = "https://api.steamcmd.net/v1/info/{appid}"
STORE_DETAILS = "https://store.steampowered.com/api/appdetails?appids={appid}"
DEPOT_NAMES = "https://raw.githubusercontent.com/Masquerade64/SteamDepotNames/main/depots.ini"

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
}

# Parses: data-ds-appid="12345" and <div class="match_name ...">Game Title</div>
_RE_APPID = re.compile(r'data-ds-appid="(\d+)"')
_RE_NAME = re.compile(r'class="match_name[^"]*">([^<]+)</div>')

PLATFORMS = {
    "Windows 64-bit": "win64",
    "Windows 32-bit": "win32",
    "Linux 64-bit": "lin64",
    "Linux 32-bit": "lin32",
    "macOS": "macos",
}

PLATFORM_STEAMCMD = {
    "win64": ("windows", "64"),
    "win32": ("windows", "32"),
    "lin64": ("linux", "64"),
    "lin32": ("linux", "32"),
    "macos": ("macos", None),
}

# Maps our platform key → Store API "platforms" object key (note: "mac" not "macos")
PLATFORM_OS = {
    "win64": "windows",
    "win32": "windows",
    "lin64": "linux",
    "lin32": "linux",
    "macos": "mac",
}

# Human-readable label for each Store API OS key
OS_DISPLAY = {
    "windows": "Windows",
    "mac": "macOS",
    "linux": "Linux",
}

# Primary (64-bit) platform key for each Store API OS key, used when expanding "all"
OS_PRIMARY_PLATFORM = {
    "windows": "win64",
    "mac": "macos",
    "linux": "lin64",
}


async def search_games(term: str) -> list[dict[str, str]]:
    """Return list of {name, appid} matching term."""
    url = STORE_SUGGEST.format(term=quote(term, safe=""))
    log.debug("search_games: GET %s", url)
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            log.debug("search_games: status %s", r.status)
            html = await r.text()

    appids = _RE_APPID.findall(html)
    names = _RE_NAME.findall(html)
    log.debug("search_games: found %d appids, %d names", len(appids), len(names))

    results = [{"appid": aid, "name": name} for aid, name in zip(appids, names)]
    log.debug("search_games: returning %s", results)
    return results


async def get_game_info(appid: str) -> dict[str, Any]:
    """Return structured game info from api.steamcmd.net."""
    url = STEAMCMD_INFO.format(appid=appid)
    log.debug("get_game_info: GET %s", url)
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            log.debug("get_game_info: status %s", r.status)
            data = await r.json(content_type=None)

    if data.get("status") != "success":
        raise ValueError(f"App {appid} not found (status: {data.get('status')})")

    app = data["data"][appid]
    common = app.get("common", {})
    depots = app.get("depots", {})
    branches = depots.get("branches", {})

    result: dict[str, Any] = {
        "appid": appid,
        "name": common.get("name", f"App {appid}"),
        "installdir": common.get("installdir", common.get("name", f"App {appid}")),
        "branches": list(branches.keys()),
        "depots": {},
    }

    for depot_id, depot_data in depots.items():
        if not depot_id.isdigit():
            continue
        # Preserve full manifest metadata so downstream code can compute
        # InstalledDepots sizes and BytesToDownload accurately.
        manifests: dict[str, dict[str, str]] = {}
        size = ""
        for branch, branch_data in depot_data.get("manifests", {}).items():
            if isinstance(branch_data, dict):
                manifests[branch] = {
                    "gid": str(branch_data.get("gid", "")),
                    "size": str(branch_data.get("size", "")),
                    "download": str(branch_data.get("download", "")),
                }
                if branch == "public":
                    size = branch_data.get("size", "")
            else:
                manifests[branch] = {"gid": str(branch_data), "size": "", "download": ""}
        result["depots"][depot_id] = {
            "name": depot_data.get("name", ""),
            "manifests": manifests,
            "depotfromapp": str(depot_data.get("depotfromapp", "")),
            "sharedinstall": str(depot_data.get("sharedinstall", "")),
            "dlcappid": str(depot_data.get("dlcappid", "")),
            "oslist": str(depot_data.get("config", {}).get("oslist", "")),
            "size": size,
        }

    for branch_name, branch_data in branches.items():
        result[f"build_{branch_name}"] = branch_data.get("buildid", "")
        ts = branch_data.get("timeupdated")
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
            result[f"time_{branch_name}"] = dt.strftime("%B %-d, %Y - %H:%M:%S UTC")
        else:
            result[f"time_{branch_name}"] = ""

    log.debug("get_game_info: name=%r branches=%r", result["name"], result["branches"])
    return result


async def get_store_details(appid: str) -> dict[str, Any]:
    """Return store details (short description, website)."""
    url = STORE_DETAILS.format(appid=appid)
    log.debug("get_store_details: GET %s", url)
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None)
    app = data.get(appid, {})
    if not app.get("success"):
        return {}
    d = app.get("data", {})
    return {
        "short_description": d.get("short_description", ""),
        "website": d.get("website") or f"https://store.steampowered.com/app/{appid}/",
        "platforms": d.get("platforms", {}),
    }


async def fetch_depot_names() -> dict[str, str]:
    """Return {depot_id: name} from Masquerade64's depot names list."""
    log.debug("fetch_depot_names: fetching")
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(DEPOT_NAMES, timeout=aiohttp.ClientTimeout(total=10)) as r:
                text = await r.text()
        names: dict[str, str] = {}
        in_section = False
        for line in text.splitlines():
            line = line.strip()
            if line.lower() == "[depots]":
                in_section = True
                continue
            if in_section and line.startswith("["):
                break
            if in_section and "=" in line:
                k, _, v = line.partition("=")
                names[k.strip()] = v.strip()
        log.debug("fetch_depot_names: loaded %d entries", len(names))
        return names
    except Exception:
        log.exception("fetch_depot_names failed")
        return {}
