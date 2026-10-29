from __future__ import annotations

import hashlib
import os
import stat
from typing import TypedDict

from .io import PathArg, resolve_path

STREAMING_CHUNK_SIZE = 1024 * 1024  # 1 MB


class FileInspection(TypedDict):
    path: str
    exists: bool | None
    size_bytes: int | None
    sha256: str | None


class FileHash(TypedDict):
    size_bytes: int
    sha256: str


def hash_file(path: PathArg, chunk_size: int = STREAMING_CHUNK_SIZE) -> FileHash:
    """Compute a file's SHA-256 digest using streamed reads."""
    path = resolve_path(path)

    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Path {path} is not a regular file.")

    digest = hashlib.sha256()

    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())

        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Path {path} is not a regular file.")

        while chunk := stream.read(chunk_size):
            digest.update(chunk)

        after = os.fstat(stream.fileno())

    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise ValueError(f"File {path} changed during hashing.")

    return {
        "size_bytes": after.st_size,
        "sha256": digest.hexdigest(),
    }


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

    if not hash_content:
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": info.st_size,
            "sha256": None,
        }

    hashed = hash_file(path)

    return {
        "path": str(path),
        "exists": True,
        "size_bytes": hashed["size_bytes"],
        "sha256": hashed["sha256"],
    }
