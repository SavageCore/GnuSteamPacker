"""BLAKE3 file hashing."""

from pathlib import Path

import blake3


def blake3_hex(path: Path) -> str:
    hasher = blake3.blake3(max_threads=blake3.blake3.AUTO)
    hasher.update_mmap(str(path))
    return hasher.hexdigest()
