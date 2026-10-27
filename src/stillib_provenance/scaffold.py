from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from stillib_provenance.io import resolve_path


def init_config(path: str | Path = "config.py") -> Path:
    """
    Create a template ``config.py`` file without overwriting existing content.

    The generated module contains an example Pydantic configuration
    model. If the destination already exists, it is left unchanged and a
    message is printed.

    Args:
        path: Destination file. Defaults to ``config.py`` in the current
            working directory. Parent directories are not created.

    Returns:
        The resolved absolute destination path.

    Raises:
        FileNotFoundError: If the destination's parent directory does not exist.
        OSError: If the template cannot be read or the destination cannot be
            written.

    Example:
        >>> init_config("config.py")
    """
    # fetch the template file shipped with this package
    template = files("stillib_provenance").joinpath("templates", "config.py.txt")

    # convert to pathlib.Path if a string is provided
    destination = resolve_path(path)

    try:
        # check if the destination file already exists and write if not
        with destination.open("x", encoding="utf-8") as f:
            f.write(template.read_text(encoding="utf-8"))
        print(f"Initialized config.py template at: {destination.resolve()}")

    except FileExistsError:
        print(f"File {destination.resolve()} already exists. No changes made.")

    return destination
