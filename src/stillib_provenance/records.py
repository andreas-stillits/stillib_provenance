from __future__ import annotations

import json
from collections.abc import Mapping
from os import PathLike
from pathlib import Path

from pydantic import BaseModel

PathArg = str | PathLike[str]  # versatile user input type for paths

# HEADER FOR MAGIC STRINGS
# --------------------------------------------
RECORD_SCHEMA_VERSION: str = "1.0"

RECORD_STATUS_RUNNING: str = "running"
RECORD_STATUS_FINISHED: str = "finished"
RECORD_STATUS_INCOMPLETE: str = "incomplete"
RECORD_STATUS_FAILED: str = "failed"

RECORD_DIRECTORY_NAME: str = "record"

CONFIG_FILE_NAME: str = "config.json"
PROVENANCE_FILE_NAME: str = "provenance.json"
# --------------------------------------------


def _resolve_path(path: PathArg) -> Path:
    return Path(path).expanduser().resolve()


def _paths(files: Mapping[str, PathArg] | None) -> dict[str, Path]:
    """
    Internal utility to convert a mapping of string keys to path-like values into a dictionary of string keys to fully resolved Path objects.
    Allows the user to provide either strings or Path objects while ensuring internal consistency.
    Defines the default behavior of expanding user home directories and resolving relative paths to absolute paths.
    Returns an empty dictionary if the input mapping is None.
    """
    return {name: _resolve_path(path) for name, path in (files or {}).items()}


class Record:

    def __init__(
        self,
        config: BaseModel,
        *,
        directory: PathArg,
        inputs: Mapping[str, PathArg] | None = None,
        outputs: Mapping[str, PathArg] | None = None,
    ) -> None:
        self.directory = _resolve_path(directory)
        self.record_root = self.directory / RECORD_DIRECTORY_NAME
        self._config_file = self.record_root / CONFIG_FILE_NAME
        self._provenance_file = self.record_root / PROVENANCE_FILE_NAME

        # prepare all provided data before writing to disk
        config_json = config.model_dump_json(indent=4)
        self._inputs = _paths(inputs)
        self._outputs = _paths(outputs)

        # identify missing files
        missing_inputs = [
            name for name, path in self._inputs.items() if not path.exists()
        ]

        # If anything is missing, raise an error
        if missing_inputs:
            raise FileNotFoundError(f"Missing input files: {', '.join(missing_inputs)}")

        # If a previos record already exists, raise an error to prevent accidental overwrite
        if self._config_file.exists() or self._provenance_file.exists():
            raise FileExistsError(
                f"Record already exists in {self.directory}. Please choose a different directory or remove the existing record."
            )

        # If these things have passed:
        #   serialization of the provided config
        #   existence of required inputs
        #   non-existence of a previous record
        # then we can safely initialize the record directory and write the initial files.
        self.status: str = RECORD_STATUS_RUNNING
        self._error_type: str | None = None

        # Create the record directory and write the initial files
        self.record_root.mkdir(parents=True, exist_ok=True)

        with self._config_file.open("x", encoding="utf-8") as file:
            file.write(config_json + "\n")

        self._save_provenance()
        return

    def _save_provenance(self) -> None:
        provenance = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "status": self.status,
            "inputs": {name: str(path) for name, path in self._inputs.items()},
            "outputs": {name: str(path) for name, path in self._outputs.items()},
        }

        if self._error_type is not None:
            provenance["error_type"] = self._error_type

        # Write to a temporary file first to avoid partial writes, then atomically replace with the final file
        temp_file = self.record_root / PROVENANCE_FILE_NAME + ".tmp"
        temp_file.write_text(
            json.dumps(provenance, indent=4) + "\n",
            encoding="utf-8",
        )
        temp_file.replace(self._provenance_file)

    def _ensure_running(self) -> None:
        if self.status != RECORD_STATUS_RUNNING:
            raise RuntimeError(f"Cannot modify a record with status '{self.status}'.")

    def add_input(self, name: str, path: PathArg) -> None:
        self._ensure_running()

        # check if already recorded
        if name in self._inputs:
            raise ValueError(f"Input '{name}' already registered.")

        resolved_path = _resolve_path(path)

        # verify existence
        if not resolved_path.exists():
            raise FileNotFoundError(f"Input file '{resolved_path}' does not exist.")

        # add to inputs
        self._inputs[name] = resolved_path

        # update the written record
        self._save_provenance()
        return

    def add_output(self, name: str, path: PathLike) -> None:
        self._ensure_running()

        # check if already recorded
        if name in self._outputs:
            raise ValueError(f"Output '{name}' already registered.")

        # add to outputs
        self._outputs[name] = _resolve_path(path)

        # update the written record
        self._save_provenance()
        return

    def finish(
        self,
    ) -> None:
        self._ensure_running()

        missing_outputs = [
            name for name, path in self._outputs.items() if not path.exists()
        ]

        self.status = (
            RECORD_STATUS_INCOMPLETE if missing_outputs else RECORD_STATUS_FINISHED
        )
        self._save_provenance()

        if missing_outputs:
            raise FileNotFoundError(
                f"Missing outputs at attempted completion: {missing_outputs}"
            )

        return

    def fail(self, exception=None) -> None:
        self._ensure_running()

        self.status = RECORD_STATUS_FAILED

        if exception is not None:
            self._error_type = type(exception).__name__

        self._save_provenance()
        return

    # Context manager support for the Record class, i.e. automatic cleanup without explicit finish/fail calls.

    def __enter__(self) -> Record:
        self._ensure_running()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if self.status == RECORD_STATUS_RUNNING:
            if exception_type is None:
                self.finish()
            else:
                self.fail(exception_value)

        return False


def start_record(
    config: BaseModel,
    *,
    directory: PathLike,  # target directory for the record
    inputs: Mapping[str, PathArg] | None = None,
    outputs: Mapping[str, PathArg] | None = None,
) -> Record:
    """Wrapper initializing a Record instance"""
    return Record(
        config,
        directory=directory,
        inputs=inputs,
        outputs=outputs,
    )
