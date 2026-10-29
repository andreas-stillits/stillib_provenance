from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from .io import PathArg, resolve_path


class GitInspection(TypedDict):
    root: str | None
    commit: str | None
    branch: str | None
    dirty: bool | None


def get_utc_now() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def get_duration(entry: str, exit: str) -> float:
    """Time difference in seconds between Record entry and exit"""
    return round(
        (datetime.fromisoformat(exit) - datetime.fromisoformat(entry)).total_seconds(),
        3,
    )


def get_entry_point() -> str | None:
    """Get the entry point of the current Python program."""
    main = sys.modules.get("__main__")
    source = getattr(main, "__file__", None)

    if not source or source.startswith("<"):
        return None

    path = resolve_path(source)
    return (Path(path.parent.name) / path.name).as_posix()


def _git(directory: Path, *args: str) -> str | None:
    """Execute a Git command, returning None if unsuccessful."""
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    return result.stdout.strip() if result.returncode == 0 else None


def inspect_git(
    git_root: PathArg | None = None,
) -> GitInspection:
    """Capture Git identity and working-tree state."""

    directory = Path.cwd() if git_root is None else resolve_path(git_root)

    root = _git(directory, "rev-parse", "--show-toplevel")

    if root is None:
        return {
            "root": None,
            "commit": None,
            "branch": None,
            "dirty": None,
        }

    repo = Path(root)

    status = _git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )

    return {
        "root": str(repo),
        "commit": _git(repo, "rev-parse", "--verify", "HEAD"),
        "branch": _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD"),
        "dirty": (None if status is None else bool(status)),
    }
