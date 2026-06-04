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
    split_mb: int = 5120,
    progress_cb: Callable[[str], None] | None = None,
) -> Path:
    """
    Compress source_dir into output_dir/<archive_name>.7z.
    Returns the path to the final archive (renamed if single-part).
    Raises RuntimeError if 7z not found or compression fails.
    """
    sevenz = find_7z()
    if not sevenz:
        raise RuntimeError(
            "7-Zip not found. Install p7zip-full (apt/dnf) or 7-zip."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_base = output_dir / archive_name
    split_size = f"{split_mb}m" if split_mb else "5120m"

    cmd = [
        sevenz, "a",
        "-mx9",
        "-sdel",
        "-pcs.rin.ru",
        "-mhe=on",
        f"-v{split_size}",
        str(out_base) + ".7z",
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

    # If only one volume was created rename .7z.001 → .7z
    part1 = Path(str(out_base) + ".7z.001")
    final = Path(str(out_base) + ".7z")
    if part1.exists() and not list(output_dir.glob(archive_name + ".7z.002")):
        part1.rename(final)
    elif part1.exists():
        final = part1

    return final
