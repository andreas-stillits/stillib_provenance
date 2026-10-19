from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def init_config(path: str | Path = "config.py") -> Path:
    """
    Initialize a new config.py template file in a specified directory.
    Does not overwrite if the file already exists.
    Simply call init_config() to emit in the current working directory.
    """
    # fetch the template file shipped with this package
    template = files("stillib_provenance").joinpath("templates", "config.py.txt")

    # convert to pathlib.Path if a string is provided
    destination = Path(path)

    try:
        # check if the destination file already exists and write if not
        with destination.open("x", encoding="utf-8") as f:
            f.write(template.read_text(encoding="utf-8"))
        print(f"Initialized config.py template at: {destination.resolve()}")

    except FileExistsError:
        print(f"File {destination.resolve()} already exists. No changes made.")

    return destination
