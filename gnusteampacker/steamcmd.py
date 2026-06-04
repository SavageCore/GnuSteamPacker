"""SteamCMD auto-install and job execution."""

import asyncio
import re
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

import aiohttp

from gnusteampacker.config import DATA_DIR
from gnusteampacker.queue_model import QueueItem
from gnusteampacker.steam_api import PLATFORM_STEAMCMD

STEAMCMD_URL = "https://media.steampowered.com/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_DEFAULT = DATA_DIR / "steamcmd" / "steamcmd.sh"

_PROGRESS_RE = re.compile(r"progress:\s+([\d.]+)", re.IGNORECASE)


async def ensure_steamcmd(path: Path, progress_cb: Callable[[str], None] | None = None) -> None:
    """Download and initialise SteamCMD if not present."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if progress_cb:
        progress_cb("Downloading SteamCMD…")
    async with aiohttp.ClientSession() as session:
        async with session.get(STEAMCMD_URL, timeout=aiohttp.ClientTimeout(total=120)) as r:
            data = await r.read()
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    with tarfile.open(tmp_path) as tf:
        tf.extractall(path.parent)
    tmp_path.unlink()
    if progress_cb:
        progress_cb("Initialising SteamCMD…")
    proc = await asyncio.create_subprocess_exec(
        str(path), "+quit",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


def _write_job(
    item: QueueItem,
    username: str,
    password: str,
    output_dir: Path,
) -> Path:
    platform, bitness = PLATFORM_STEAMCMD[item.platform]
    lines = [
        "@ShutdownOnFailedCommand 1",
        "@NoPromptForPassword 1",
    ]
    if password:
        lines.append(f"login {username} {password}")
    else:
        lines.append(f"login {username}")
    lines.append(f"@sSteamCmdForcePlatformType {platform}")
    if bitness:
        lines.append(f"@sSteamCmdForcePlatformBitness {bitness}")
    lines.append(f"force_install_dir {output_dir}")
    app_cmd = f"app_update {item.appid}"
    if item.branch and item.branch != "public":
        app_cmd += f" -beta {item.branch}"
        if item.branch_password:
            app_cmd += f" -betapassword {item.branch_password}"
    app_cmd += " validate"
    lines.append(app_cmd)
    lines.append("quit")

    job_file = Path(tempfile.mktemp(suffix=".job", prefix="gnusteampacker_"))
    job_file.write_text("\n".join(lines) + "\n")
    return job_file


async def run_download(
    item: QueueItem,
    steamcmd_path: Path,
    username: str,
    password: str,
    output_dir: Path,
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[bool, str]:
    """Run SteamCMD for item. Returns (success, error_reason)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    job = _write_job(item, username, password, output_dir)
    try:
        proc = await asyncio.create_subprocess_exec(
            str(steamcmd_path),
            f"+runscript {job}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(steamcmd_path.parent),
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            m = _PROGRESS_RE.search(line)
            if m and progress_cb:
                pct = float(m.group(1)) / 100.0
                progress_cb(pct, line)
        await proc.wait()
    finally:
        job.unlink(missing_ok=True)

    return _check_logs(steamcmd_path.parent)


def _check_logs(steamcmd_dir: Path) -> tuple[bool, str]:
    logs = steamcmd_dir / "logs"

    def read(name: str) -> str:
        p = logs / name
        return p.read_text(errors="replace") if p.exists() else ""

    content = read("content_log.txt")
    connection = read("connection_log.txt")
    combined = content + connection

    if "No subscription" in content:
        return False, "nosub"
    if "Rate Limit Exceeded" in connection:
        return False, "ratelimited"
    if "Invalid Password" in connection:
        return False, "badlogin"
    # Positive Steam Guard failure: SteamCMD explicitly says auth failed
    steamguard_errors = (
        "Two-factor code mismatch",
        "Steam Guard",
        "requires two-factor",
        "steamguard",
    )
    if any(s.lower() in combined.lower() for s in steamguard_errors):
        return False, "steamguard"
    return True, ""
