"""SteamCMD auto-install and job execution."""

import asyncio
import logging
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

log = logging.getLogger(__name__)

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
        f"force_install_dir {output_dir}",
    ]
    if password:
        lines.append(f"login {username} {password}")
    else:
        lines.append(f"login {username}")  # uses ~/.local/share/Steam/ cached credentials
    lines.append(f"@sSteamCmdForcePlatformType {platform}")
    if bitness:
        lines.append(f"@sSteamCmdForcePlatformBitness {bitness}")
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
    log.debug("SteamCMD job script:\n%s", job.read_text())
    cmd = [str(steamcmd_path), "+runscript", str(job)]
    log.debug("Running: %s  (cwd=%s)", " ".join(cmd), steamcmd_path.parent)
    stdout_lines: list[str] = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(steamcmd_path.parent),
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            stdout_lines.append(line)
            log.debug("[steamcmd] %s", line)
            if progress_cb:
                m = _PROGRESS_RE.search(line)
                if m:
                    progress_cb(float(m.group(1)) / 100.0, line)
                elif "Logging in" in line:
                    progress_cb(0.0, line)
        await proc.wait()
        log.debug("SteamCMD exited with code %s", proc.returncode)
    finally:
        job.unlink(missing_ok=True)

    return _check_logs(steamcmd_path.parent, "\n".join(stdout_lines))


def _check_logs(steamcmd_dir: Path, stdout: str = "") -> tuple[bool, str]:
    logs = steamcmd_dir / "logs"

    def read(name: str) -> str:
        p = logs / name
        return p.read_text(errors="replace") if p.exists() else ""

    content = read("content_log.txt")
    connection = read("connection_log.txt")
    log.debug("content_log.txt:\n%s", content or "(empty)")
    log.debug("connection_log.txt:\n%s", connection or "(empty)")

    if "Success! App" in stdout:
        return True, ""

    combined = stdout + content + connection
    if "No subscription" in combined:
        return False, "nosub"
    if "Rate Limit Exceeded" in combined:
        return False, "ratelimited"
    if "Invalid Password" in combined:
        return False, "badlogin"
    steamguard_errors = (
        "Two-factor code mismatch",
        "Wait for confirmation timed out",
        "Timed out waiting for confirmation",
        "requires two-factor",
    )
    if any(s in combined for s in steamguard_errors):
        return False, "steamguard"
    return True, ""
