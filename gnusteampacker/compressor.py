"""7z compression wrapper."""

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path


def find_7z() -> str | None:
    for candidate in ("7z", "7za", "7zz"):
        if shutil.which(candidate):
            return candidate
    return None


async def compress(
    source_dir: Path,
    archive_name: str,
    output_dir: Path,
    progress_cb: Callable[[str], None] | None = None,
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

    cmd = [
        sevenz, "a",
        f"-mx{level}",
        f"-mmt={threads}",
        "-sdel",
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
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        if progress_cb and line.strip():
            progress_cb(line)
    await proc.wait()

    if proc.returncode not in (0, 1):
        raise RuntimeError(f"7z exited with code {proc.returncode}")

    return out_path
