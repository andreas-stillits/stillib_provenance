from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


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
    git_root: str | Path | None = None,
) -> dict:
    """Capture Git identity and working-tree state."""

    directory = (
        Path.cwd() if git_root is None else Path(git_root).expanduser().resolve()
    )

    root = _git(directory, "rev-parse", "--show-toplevel")

    if root is None:
        return {
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
        "commit": _git(repo, "rev-parse", "--verify", "HEAD"),
        "branch": _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD"),
        "dirty": (None if status is None else bool(status)),
    }
