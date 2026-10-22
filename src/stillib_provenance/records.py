from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Self

from pydantic import BaseModel

from .context import inspect_git, utc_now
from .inspection import inspect_file
from .io import resolve_path

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


def _paths(files: Mapping[str, PathArg] | None) -> dict[str, Path]:
    """
    Internal utility to convert a mapping of string keys to path-like values into a dictionary of string keys to fully resolved Path objects.
    Allows the user to provide either strings or Path objects while ensuring internal consistency.
    Defines the default behavior of expanding user home directories and resolving relative paths to absolute paths.
    Returns an empty dictionary if the input mapping is None.
    """
    return {name: resolve_path(path) for name, path in (files or {}).items()}


class Record:

    def __init__(
        self,
        config: BaseModel,
        *,
        directory: PathArg,
        inputs: Mapping[str, PathArg] | None = None,
        outputs: Mapping[str, PathArg] | None = None,
        hash_files: bool = True,
        git_root: PathArg | None = None,
    ) -> None:
        self.directory = resolve_path(directory)
        self.record_root = self.directory / RECORD_DIRECTORY_NAME
        self._config_file = self.record_root / CONFIG_FILE_NAME
        self._provenance_file = self.record_root / PROVENANCE_FILE_NAME
        self._hash_files = hash_files
        self._git_root = resolve_path(git_root) if git_root is not None else None
        self._git_info = inspect_git(self._git_root)

        # prepare all provided data before writing to disk
        config_json = config.model_dump_json(
            indent=4, round_trip=True, warnings="error"
        )
        self._input_paths = _paths(inputs)
        self._output_paths = _paths(outputs)

        # identify missing files
        missing_inputs = [
            name for name, path in self._input_paths.items() if not path.exists()
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

        # upgrade inputs to include file metadata
        self._inputs = {
            name: {
                "path": str(path),
                **inspect_file(path, hash_content=self._hash_files),
            }
            for name, path in self._input_paths.items()
        }

        # postbone hashing of outputs until finish().
        # Intention is declared at __init__, but files are not guaranteed to exist until finish()
        self._outputs = {
            name: {
                "path": str(path),
                **inspect_file(
                    None, hash_content=self._hash_files
                ),  # pass None to get an empty schema back
            }
            for name, path in self._output_paths.items()
        }

        # Create the record directory and write the config file only AFTER all verification
        self.record_root.mkdir(parents=True, exist_ok=True)

        with self._config_file.open("x", encoding="utf-8") as file:
            file.write(config_json + "\n")

        self._time_entry = utc_now()  # record the time of record creation
        self._time_exit = None  # will be set when the record is finished or failed
        self._duration = None  # will be set when the record is finished or failed
        self._save_provenance()

    def _save_provenance(self) -> None:
        provenance = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "entry": self._time_entry,
            "exit": self._time_exit,
            "duration_seconds": self._duration,
            "status": self.status,
            "git": self._git_info,
            "inputs": {name: data for name, data in self._inputs.items()},
            "outputs": {name: data for name, data in self._outputs.items()},
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

        resolved_path = resolve_path(path)

        # verify existence
        if not resolved_path.exists():
            raise FileNotFoundError(f"Input file '{resolved_path}' does not exist.")

        # add to inputs
        self._inputs[name] = {
            "path": str(resolved_path),
            **inspect_file(resolved_path, hash_content=self._hash_files),
        }

        # update the written record
        self._save_provenance()
        return

    def add_output(self, name: str, path: PathArg) -> None:
        self._ensure_running()

        # check if already recorded
        if name in self._outputs:
            raise ValueError(f"Output '{name}' already registered.")

        # add to outputs
        self._outputs[name] = {
            "path": str(resolve_path(path)),
            **inspect_file(None, hash_content=self._hash_files),
        }

        # update the written record
        self._save_provenance()

    def finish(
        self,
    ) -> None:
        self._ensure_running()
        self._time_exit = utc_now()
        self._duration = round(
            (
                datetime.fromisoformat(self._time_exit)
                - datetime.fromisoformat(self._time_entry)
            ).total_seconds(),
            3,
        )

        missing_outputs = [
            name
            for name, data in self._outputs.items()
            if not Path(data["path"]).exists()
        ]

        if missing_outputs:
            message = f"Missing expected outputs: {missing_outputs}"
            self._error = {
                "type": "MissingOutputs",
                "message": message,
            }
            self.status = RECORD_STATUS_INCOMPLETE
            self._save_provenance()
            raise FileNotFoundError(message)
        else:
            self._outputs = {
                name: {
                    "path": str(data["path"]),
                    **inspect_file(data["path"], hash_content=self._hash_files),
                }
                for name, data in self._outputs.items()
            }

            self.status = RECORD_STATUS_FINISHED
            self._save_provenance()

    def fail(self, exception=None) -> None:
        self._ensure_running()
        self._time_exit = utc_now()
        self._duration = round(
            (
                datetime.fromisoformat(self._time_exit)
                - datetime.fromisoformat(self._time_entry)
            ).total_seconds(),
            3,
        )

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
    hash_files: bool = True,
    git_root: PathArg | None = None,
) -> Record:
    """Factory initializing a Record instance"""
    # later potentially inspect metadata first ...
    return Record(
        config,
        directory=directory,
        inputs=inputs,
        outputs=outputs,
        hash_files=hash_files,
        git_root=git_root,
    )
