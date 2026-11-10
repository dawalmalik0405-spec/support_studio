"""Helpers for detecting changed input files."""

import hashlib
from pathlib import Path


def calculate_file_fingerprint(file_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
