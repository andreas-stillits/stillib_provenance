"""
Validated configuration and provenance recording for reproducible runs.

Use ``load_config`` to build a Pydantic configuration and ``start_record`` to
capture that configuration together with input, output, Git, and timing
metadata.

Typical use:

    >>> config = load_config(Config, source="config.json")

    >>> with start_record(config, directory="runs/001") as record:
    ...     record.add_input("source", "data/source.csv")
    ...     record.add_output("result", "results/result.csv")
    ...     run(config)
        # cleanup triggered automatically when exiting the with block
"""

from .io import load_config, load_provenance, save_config, update_config
from .records import Record, start_record
from .scaffold import init_config

__all__ = [
    "init_config",
    "load_config",
    "load_provenance",
    "save_config",
    "update_config",
    "start_record",
    "Record",
]
