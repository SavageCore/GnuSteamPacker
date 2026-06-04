"""Steam public API helpers — no API key required."""

from datetime import UTC, datetime
from typing import Any

import aiohttp

STEAMCMD_INFO = "https://api.steamcmd.net/v1/info/{appid}"
STORE_SEARCH = "https://store.steampowered.com/api/storeearch/?term={term}&l=english&cc=US"
STORE_DETAILS = "https://store.steampowered.com/api/appdetails?appids={appid}"
DEPOT_NAMES = "https://raw.githubusercontent.com/Masquerade64/SteamDepotNames/main/depots.ini"

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


async def search_games(term: str) -> list[dict[str, str]]:
    """Return list of {name, appid} matching term."""
    async with aiohttp.ClientSession() as session:
        url = STORE_SEARCH.format(term=aiohttp.helpers.quote(term, safe=""))
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json(content_type=None)
    items = data.get("items", [])
    return [{"name": i["name"], "appid": str(i["id"])} for i in items if i.get("type") == "game"]


async def get_game_info(appid: str) -> dict[str, Any]:
    """Return structured game info from api.steamcmd.net."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            STEAMCMD_INFO.format(appid=appid), timeout=aiohttp.ClientTimeout(total=15)
        ) as r:
            data = await r.json(content_type=None)

    if data.get("status") != "success":
        raise ValueError(f"App {appid} not found")

    app = data["data"][appid]
    common = app.get("common", {})
    depots = app.get("depots", {})
    branches = depots.get("branches", {})

    branch_names = list(branches.keys())

    result: dict[str, Any] = {
        "appid": appid,
        "name": common.get("name", f"App {appid}"),
        "branches": branch_names,
        "depots": {},
    }

    for depot_id, depot_data in depots.items():
        if not depot_id.isdigit():
            continue
        manifests = depot_data.get("manifests", {})
        result["depots"][depot_id] = {
            "name": depot_data.get("name", ""),
            "manifests": manifests,
        }

    for branch_name, branch_data in branches.items():
        result[f"build_{branch_name}"] = branch_data.get("buildid", "")
        ts = branch_data.get("timeupdated")
        if ts:
            dt = datetime.fromtimestamp(int(ts), tz=UTC)
            result[f"time_{branch_name}"] = dt.strftime("%Y-%m-%d %H:%M UTC")
        else:
            result[f"time_{branch_name}"] = ""

    return result


async def get_store_details(appid: str) -> dict[str, Any]:
    """Return store details (short description, website)."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            STORE_DETAILS.format(appid=appid), timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json(content_type=None)
    app = data.get(appid, {})
    if not app.get("success"):
        return {}
    d = app.get("data", {})
    return {
        "short_description": d.get("short_description", ""),
        "website": d.get("website") or f"https://store.steampowered.com/app/{appid}/",
    }


async def fetch_depot_names() -> dict[str, str]:
    """Return {depot_id: name} from Masquerade64's depot names list."""
    try:
        async with aiohttp.ClientSession() as session:
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
        return names
    except Exception:
        return {}
