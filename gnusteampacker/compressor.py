"""7z compression wrapper."""

import asyncio
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from gnusteampacker.speed import SpeedTracker

_PERCENT_RE = re.compile(r"(\d{1,3})%")


def find_7z() -> str | None:
    for candidate in ("7z", "7za", "7zz"):
        if shutil.which(candidate):
            return candidate
    return None


async def compress(
    source_dir: Path,
    archive_name: str,
    output_dir: Path,
    progress_cb: Callable[[float, float], None] | None = None,
    level: int = 5,
    threads: int = 1,
) -> Path:
    """
    Compress source_dir into output_dir/<archive_name>.7z.
    Raises RuntimeError if 7z not found or compression fails.
    """
    sevenz = find_7z()
    if not sevenz:
        raise RuntimeError("7-Zip not found. Install p7zip-full (apt/dnf) or 7-zip.")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / (archive_name + ".7z")

    total_size = sum(f.stat().st_size for f in source_dir.rglob("*") if f.is_file())

    cmd = [
        sevenz,
        "a",
        f"-mx{level}",
        f"-mmt={threads}",
        "-bsp1",
        "-pcs.rin.ru",
        "-mhe=on",
        str(out_path),
        "*",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(source_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None

    speed_tracker = SpeedTracker()
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        if not progress_cb:
            continue
        text = chunk.decode(errors="replace")
        matches = _PERCENT_RE.findall(text)
        if not matches:
            continue
        pct = int(matches[-1])
        downloaded = int(total_size * pct / 100)
        speed = speed_tracker.update(downloaded)
        progress_cb(pct / 100, speed)
    await proc.wait()

    if proc.returncode not in (0, 1):
        raise RuntimeError(f"7z exited with code {proc.returncode}")

    return out_path
