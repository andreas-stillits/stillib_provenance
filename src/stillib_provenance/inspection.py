from __future__ import annotations

import hashlib
import os
import stat
from typing import Any, TypedDict

from .io import PathArg, resolve_path

STREAMING_CHUNK_SIZE = 1024 * 1024  # 1 MB


class FileInspection(TypedDict):
    path: str
    exists: bool | None
    size_bytes: int | None
    sha256: str | None


def inspect_file(
    path: PathArg,
    *,
    hash_content: bool = True,
) -> FileInspection:
    """
    Utility function to inspect a file at a given path.
    Returns a dictionary containing: existence, size in bytes, and SHA256 hash (if requested).
    Raises ValueError if the path is not a regular file or if the file changes during hashing

    Design choices:
        - Accept only regular files for now. Does not promise identity for directories or special files.
        - SHA-256 hashing is streamed to avoid loading large files into memory.
        - Missing files are just reported to Record, not raised as exceptions locally.
        - Tries to catch if a file is modified by another process during hashing by checking size and modification time before and after reading.
    """

    path = resolve_path(path)

    try:
        info = path.stat()
    except FileNotFoundError:
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": None,
            "sha256": None,
        }

    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Path {path} is not a regular file.")

    if not hash_content:
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": info.st_size,
            "sha256": None,
        }

    digest = hashlib.sha256()

    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())

        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Path {path} is not a regular file.")

        while chunk := stream.read(STREAMING_CHUNK_SIZE):
            digest.update(chunk)

        after = os.fstat(stream.fileno())

    if (before.st_size != after.st_size) or (before.st_mtime != after.st_mtime):
        raise ValueError(f"File {path} changed during hashing.")

    return {
        "path": str(path),
        "exists": True,
        "size_bytes": after.st_size,
        "sha256": digest.hexdigest(),
    }
