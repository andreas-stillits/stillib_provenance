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


class FileRecord:
    def __init__(self, name: str, path: PathArg, hash_content: bool) -> None:
        self.name = name
        self.path = resolve_path(path)
        self.hash_content = hash_content

        self.exists: bool | None = None
        self.size_bytes: int | None = None
        self.sha256: str | None = None

    def inspect(self) -> Self:
        result: dict = inspect_file(self.path, hash_content=self.hash_content)

        self.exists = result["exists"]
        self.size_bytes = result["size_bytes"]
        self.sha256 = result["sha256"]
        return self

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


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

        # serialize the provided config to JSON for storage
        config_json = config.model_dump_json(
            indent=4, round_trip=True, warnings="error"
        )

        # If a previos record already exists, raise an error to prevent accidental overwrite
        if self._config_file.exists() or self._provenance_file.exists():
            raise FileExistsError(
                f"Record already exists in {self.directory}. Please choose a different directory or remove the existing record."
            )

        # register the provided input and output paths
        self._inputs = [
            FileRecord(name, path, self._hash_files)
            for name, path in (inputs or {}).items()
        ]
        self._outputs = [
            FileRecord(name, path, self._hash_files)
            for name, path in (outputs or {}).items()
        ]

        # inspect all declared inputs
        missing_inputs = []
        for input in self._inputs:
            input = input.inspect()
            if not input.exists:
                missing_inputs.append(input.path)

        if missing_inputs:
            raise FileNotFoundError(f"Missing input files: {missing_inputs}")

        # If these things have passed:
        #   serialization of the provided config
        #   existence of required inputs
        #   non-existence of a previous record
        # then we can safely initialize the record directory and write the initial files.
        self.status: str = RECORD_STATUS_RUNNING
        self._error: dict | None = None

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
            "inputs": {input.name: input.as_dict() for input in self._inputs},
            "outputs": {output.name: output.as_dict() for output in self._outputs},
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
        if name in [input.name for input in self._inputs]:
            raise ValueError(f"Input '{name}' already registered.")

        # declare the input
        input = FileRecord(name, path, self._hash_files)
        self._inputs.append(input)

        # inspect it
        input.inspect()
        if not input.exists:
            raise FileNotFoundError(f"Input file '{input.path}' does not exist.")

        # update the written record
        self._save_provenance()

    def add_output(self, name: str, path: PathArg) -> None:
        self._ensure_running()

        # check if already recorded
        if name in [output.name for output in self._outputs]:
            raise ValueError(f"Output '{name}' already registered.")

        # declare the output
        self._outputs.append(FileRecord(name, path, self._hash_files))

        # update the written record
        self._save_provenance()

    def _terminate(self) -> None:
        self._time_exit = utc_now()
        self._duration = round(
            (
                datetime.fromisoformat(self._time_exit)
                - datetime.fromisoformat(self._time_entry)
            ).total_seconds(),
            3,
        )

    def finish(
        self,
    ) -> None:
        self._ensure_running()
        self._terminate()

        # inspect all outputs
        missing_outputs = []
        for output in self._outputs:
            output = output.inspect()
            if not output.exists:
                missing_outputs.append(output.path)

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
            self.status = RECORD_STATUS_FINISHED
            self._save_provenance()

    def fail(self, exception=None) -> None:
        self._ensure_running()
        self._terminate()

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
