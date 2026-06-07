"""DepotDownloader auto-install and job execution."""

import asyncio
import logging
import re
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import aiohttp

from gnusteampacker.config import DATA_DIR
from gnusteampacker.queue_model import QueueItem
from gnusteampacker.steam_api import PLATFORM_STEAMCMD

DD_DEFAULT = DATA_DIR / "depotdownloader" / "DepotDownloader"
_GITHUB_LATEST = "https://api.github.com/repos/SteamRE/DepotDownloader/releases/latest"
_ASSET_SUFFIX = "linux-x64.zip"

log = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"(\d+\.\d+)%")


async def ensure_depotdownloader(
    path: Path, progress_cb: Callable[[str], None] | None = None
) -> None:
    """Download and install DepotDownloader if not present."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb("Fetching DepotDownloader release info…")
    headers = {"User-Agent": "GnuSteamPacker"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(_GITHUB_LATEST, timeout=aiohttp.ClientTimeout(total=15)) as r:
            release = await r.json(content_type=None)
    asset_url = next(
        (
            a["browser_download_url"]
            for a in release.get("assets", [])
            if a["name"].endswith(_ASSET_SUFFIX)
        ),
        None,
    )
    if not asset_url:
        raise RuntimeError("Could not find DepotDownloader linux-x64 release asset")
    if progress_cb:
        progress_cb("Downloading DepotDownloader…")
    async with aiohttp.ClientSession() as session:
        async with session.get(asset_url, timeout=aiohttp.ClientTimeout(total=120)) as r:
            data = await r.read()
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(path.parent)
    finally:
        tmp_path.unlink()
    path.chmod(0o755)
    if progress_cb:
        progress_cb("DepotDownloader ready.")


async def run_download(
    item: QueueItem,
    dd_path: Path,
    username: str,
    password: str,
    install_dir: Path,
    progress_cb: Callable[[float, str], None] | None = None,
    steam_guard_code: str | None = None,
    remember_login: bool = True,
    skip_app_confirmation: bool = False,
) -> tuple[bool, str]:
    """Run DepotDownloader for item. Returns (success, error_reason)."""
    install_dir.mkdir(parents=True, exist_ok=True)

    platform, arch = PLATFORM_STEAMCMD[item.platform]
    cmd = [
        str(dd_path),
        "-app",
        str(item.appid),
        "-os",
        platform,
        "-dir",
        str(install_dir),
    ]
    use_qr = username.lower() == "qr"
    if use_qr:
        cmd += ["-qr"]
    else:
        cmd += ["-username", username]
        if remember_login:
            cmd += ["-remember-password"]
        if skip_app_confirmation:
            cmd += ["-no-mobile"]
    if arch:
        cmd += ["-osarch", arch]
    if password and not use_qr:
        cmd += ["-password", password]

    branch = item.branch or "public"
    if branch != "public":
        cmd += ["-branch", branch]
        if item.branch_password:
            cmd += ["-branchpassword", item.branch_password]

    log.debug("Running DepotDownloader: %s", " ".join(str(c) for c in cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(dd_path.parent),
    )

    output, sg_reason = await _stream_with_guard(proc, steam_guard_code, progress_cb)

    if sg_reason:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return False, sg_reason

    await proc.wait()
    log.debug("DepotDownloader exited %s", proc.returncode)
    return _check_output(output, proc.returncode)


async def _stream_with_guard(
    proc,
    steam_guard_code: str | None,
    progress_cb,
) -> tuple[str, str | None]:
    """Read process stdout, handling Steam Guard prompts via stdin."""
    buf = b""
    lines: list[str] = []

    assert proc.stdout is not None
    assert proc.stdin is not None

    while True:
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=60.0)
        except TimeoutError:
            decoded = buf.decode(errors="replace")
            if "STEAM GUARD!" in decoded:
                if steam_guard_code:
                    proc.stdin.write((steam_guard_code + "\n").encode())
                    await proc.stdin.drain()
                    buf = b""
                    steam_guard_code = None
                else:
                    return "\n".join(lines), "steamguard"
            continue

        if not chunk:
            if buf:
                lines.append(buf.decode(errors="replace").rstrip("\r\n"))
            break

        buf += chunk
        decoded = buf.decode(errors="replace")

        if "STEAM GUARD!" in decoded:
            # Extract any complete lines before the prompt
            while b"\n" in buf:
                line_bytes, buf = buf.split(b"\n", 1)
                line = line_bytes.decode(errors="replace").rstrip("\r")
                lines.append(line)
                log.debug("[dd] %s", line)
            if steam_guard_code:
                proc.stdin.write((steam_guard_code + "\n").encode())
                await proc.stdin.drain()
                buf = b""
                steam_guard_code = None
            else:
                return "\n".join(lines), "steamguard"
            continue

        while b"\n" in buf:
            line_bytes, buf = buf.split(b"\n", 1)
            line = line_bytes.decode(errors="replace").rstrip("\r")
            lines.append(line)
            log.debug("[dd] %s", line)
            if progress_cb:
                m = _PROGRESS_RE.search(line)
                if m:
                    progress_cb(float(m.group(1)) / 100.0, line)
                elif "Downloading depot" in line:
                    progress_cb(0.0, line)

    return "\n".join(lines), None


async def run_manifest_only(
    item: QueueItem,
    dd_path: Path,
    username: str,
    password: str,
    install_dir: Path,
    progress_cb: Callable[[float, str], None] | None = None,
    remember_login: bool = True,
    skip_app_confirmation: bool = False,
) -> tuple[bool, str]:
    """Run DepotDownloader with -manifest-only to fetch .manifest files without game content."""
    install_dir.mkdir(parents=True, exist_ok=True)

    platform, arch = PLATFORM_STEAMCMD[item.platform]
    cmd = [
        str(dd_path),
        "-app",
        str(item.appid),
        "-os",
        platform,
        "-dir",
        str(install_dir),
        "-manifest-only",
    ]
    use_qr = username.lower() == "qr"
    if use_qr:
        cmd += ["-qr"]
    else:
        cmd += ["-username", username]
        if remember_login:
            cmd += ["-remember-password"]
        if skip_app_confirmation:
            cmd += ["-no-mobile"]
    if arch:
        cmd += ["-osarch", arch]
    if password and not use_qr:
        cmd += ["-password", password]

    branch = item.branch or "public"
    if branch != "public":
        cmd += ["-branch", branch]
        if item.branch_password:
            cmd += ["-branchpassword", item.branch_password]

    log.debug("Running DepotDownloader (manifest-only): %s", " ".join(str(c) for c in cmd))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(dd_path.parent),
    )

    output, sg_reason = await _stream_with_guard(proc, None, progress_cb)

    if sg_reason:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return False, sg_reason

    await proc.wait()
    log.debug("DepotDownloader (manifest-only) exited %s", proc.returncode)
    if proc.returncode == 0:
        return True, ""
    return _check_output(output, proc.returncode)


def _check_output(output: str, returncode: int | None) -> tuple[bool, str]:
    if "Total downloaded:" in output:
        return True, ""
    if "is not available from this account" in output or "No subscription" in output:
        return False, "nosub"
    badlogin_errors = (
        "Invalid Password",
        "Unable to get steam3",
        "Invalid refresh token",
        "refresh token is invalid",
        "refresh token expired",
        "refresh token revoked",
    )
    if any(s in output for s in badlogin_errors):
        return False, "badlogin"
    if "Two-factor code mismatch" in output or "previous 2-factor auth code" in output:
        return False, "steamguard"
    if "was not completely downloaded" in output:
        return False, "fail"
    if returncode == 0:
        return True, ""
    return False, "fail"


def clear_cached_login(dd_path: Path) -> None:
    """Clear DepotDownloader cached auth data."""
    cache_dir = dd_path.parent / ".DepotDownloader"
    if not cache_dir.exists():
        return
    for path in cache_dir.rglob("*"):
        if path.is_file():
            path.unlink(missing_ok=True)
