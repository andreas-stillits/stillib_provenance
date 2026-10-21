from __future__ import annotations

import json
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import Self

from pydantic import BaseModel

PathArg = str | PathLike[str]  # versatile user input type for paths

# HEADER FOR MAGIC STRINGS
# --------------------------------------------
RECORD_SCHEMA_VERSION: str = "1.0"

RECORD_STATUS_RUNNING: str = (
    "running"  # all declared input files are present, config is serializable
)
RECORD_STATUS_FINISHED: str = (
    "finished"  # all declared outputs files are present (OBS: presence does not imply content)
)
RECORD_STATUS_INCOMPLETE: str = "incomplete"  # some declared outputs are not present
RECORD_STATUS_FAILED: str = "failed"  # 'something' raised any exception

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
            raise FileNotFoundError(f"Missing input files: {missing_inputs}")

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
        self._error: dict | None = None

        # Create the record directory and write the initial files
        self.record_root.mkdir(parents=True, exist_ok=True)

        with self._config_file.open("x", encoding="utf-8") as file:
            file.write(config_json + "\n")

        self._save_provenance()

    def _save_provenance(self) -> None:
        provenance = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "status": self.status,
            "inputs": {name: str(path) for name, path in self._inputs.items()},
            "outputs": {name: str(path) for name, path in self._outputs.items()},
        }

        if self._error is not None:
            provenance["error"] = self._error

        # Write to a temporary file first to avoid partial writes, then atomically replace with the final file
        temp_file_name = PROVENANCE_FILE_NAME + ".tmp"
        temp_file = self.record_root / temp_file_name
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

    def add_output(self, name: str, path: PathArg) -> None:
        self._ensure_running()

        # check if already recorded
        if name in self._outputs:
            raise ValueError(f"Output '{name}' already registered.")

        # add to outputs
        self._outputs[name] = _resolve_path(path)

        # update the written record
        self._save_provenance()

    def finish(
        self,
    ) -> None:
        self._ensure_running()

        missing_outputs = [
            name for name, path in self._outputs.items() if not path.exists()
        ]

        if missing_outputs:
            message = f"Missing expected outputs: {missing_outputs}"
            self.status = RECORD_STATUS_INCOMPLETE
            self._error = {
                "type": "MissingOutputs",
                "message": message,
            }
            self._save_provenance()
            raise FileNotFoundError(message)
        else:
            self.status = RECORD_STATUS_FINISHED
            self._save_provenance()

    def fail(self, exception=None) -> None:
        self._ensure_running()

        self.status = RECORD_STATUS_FAILED

        if exception is not None:
            self._error = {
                "type": type(exception).__name__,
                "message": str(exception),
            }

        self._save_provenance()

    # Context manager support for the Record class, i.e. automatic cleanup without explicit finish/fail calls.

    def __enter__(self) -> Self:
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
    directory: PathArg,  # target directory for the record
    inputs: Mapping[str, PathArg] | None = None,
    outputs: Mapping[str, PathArg] | None = None,
) -> Record:
    """Factory initializing a Record instance"""
    # later potentially inspect metadata first ...
    return Record(
        config,
        directory=directory,
        inputs=inputs,
        outputs=outputs,
    )
