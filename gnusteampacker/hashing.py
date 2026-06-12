"""BLAKE3 file hashing."""

from collections.abc import Callable
from pathlib import Path

import blake3

from gnusteampacker.speed import SpeedTracker

_CHUNK_SIZE = 64 * 1024 * 1024  # 64 MiB


def blake3_hex(path: Path, progress_cb: Callable[[float, float], None] | None = None) -> str:
    hasher = blake3.blake3(max_threads=blake3.blake3.AUTO)
    total_size = path.stat().st_size
    speed_tracker = SpeedTracker()
    bytes_read = 0
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            hasher.update(chunk)
            bytes_read += len(chunk)
            if progress_cb:
                pct = bytes_read / total_size if total_size else 0.0
                progress_cb(pct, speed_tracker.update(bytes_read))
    return hasher.hexdigest()
