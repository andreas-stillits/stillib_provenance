from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from pydantic import BaseModel

from .context import GitInspection, get_duration, get_utc_now, inspect_git
from .inspection import FileInspection, hash_file, inspect_file
from .io import PathArg, resolve_path, save_config

# HEADER FOR MAGIC STRINGS
# --------------------------------------------
RECORD_SCHEMA_VERSION: str = "2.0"
CONFIG_FILE_NAME: str = "config.json"
PROVENANCE_FILE_NAME: str = "provenance.json"
# --------------------------------------------

RecordStatus = Literal[
    "running",  # all declared input files are present, config is serializable
    "finished",  # all declared outputs files are present (OBS: presence does not imply content)
    "incomplete",  # some declared outputs are not present
    "failed",  # 'something' raised any exception
]


class _RequiredProvenancePayload(TypedDict):
    schema_version: str
    entry: str
    exit: str | None
    duration_seconds: float | None
    status: RecordStatus
    config: dict[str, str | None]
    git: GitInspection
    inputs: dict[str, FileInspection]
    outputs: dict[str, FileInspection]


class ProvenancePayload(_RequiredProvenancePayload, total=False):
    # non-required fields that may be present in the provenance record
    # using inheritance rather than typing.NotRequired for python-3.10 compatibility
    annotations: dict[str, Any]
    error: dict[str, str]


class _FileRecord:
    def __init__(self, path: PathArg, hash_content: bool) -> None:
        self.path = resolve_path(path)
        self.hash_content = hash_content

        self.exists: bool | None = None
        self.size_bytes: int | None = None
        self.sha256: str | None = None

    def inspect(self) -> None:
        result = inspect_file(self.path, hash_content=self.hash_content)

        self.exists = result["exists"]
        self.size_bytes = result["size_bytes"]
        self.sha256 = result["sha256"]

    def as_dict(self) -> FileInspection:
        return {
            "path": str(self.path),
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


class Record:
    """
    A writable provenance record for one program run.

    Create records with ``start_record`` rather than constructing this class
    directly. Inputs are inspected when they are registered; outputs are
    inspected when the record is finished.

    A record starts with status ``"running"`` and can transition once to:

    - ``"finished"`` when every declared output exists.
    - ``"incomplete"`` when a declared output is missing.
    - ``"failed"`` when the recorded operation raises an exception.

    Use the record as a context manager whenever possible. Normal context
    exit calls ``finish()``; exceptional exit calls ``fail()`` and does not
    suppress the original exception.

    Attributes:
        directory: Directory containing ``config.json`` and
            ``provenance.json``.
        status: Current lifecycle status of the record.
    """

    def __init__(
        self,
        config: BaseModel,
        *,
        directory: PathArg,
        inputs: Mapping[str, PathArg] | None = None,
        outputs: Mapping[str, PathArg] | None = None,
        annotations: Mapping[str, Any] | None = None,
        hash_files: bool = True,
        force_replace: bool = False,
        git_root: PathArg | None = None,
    ) -> None:
        self.annotations = dict(annotations) if annotations is not None else {}
        self.directory = resolve_path(directory)
        self._config_file = self.directory / CONFIG_FILE_NAME
        self._provenance_file = self.directory / PROVENANCE_FILE_NAME
        self._hash_files = hash_files
        self._git_root = resolve_path(git_root) if git_root is not None else None
        self._git_info = inspect_git(self._git_root)

        # If a previos record already exists, raise an error to prevent accidental overwrite
        if not force_replace and (
            self._config_file.exists() or self._provenance_file.exists()
        ):
            raise FileExistsError(
                f"Record already exists in {self.directory}. Please choose a different directory or remove the existing record."
            )

        self._time_entry = get_utc_now()  # record the time of record creation
        self._time_exit: str | None = (
            None  # will be set when the record is finished or failed
        )
        self._duration: float | None = (
            None  # includes input and output hashing to better reflect practical cost
        )

        # register the provided input and output paths
        self._inputs = {
            name: _FileRecord(path, self._hash_files)
            for name, path in (inputs or {}).items()
        }

        self._outputs = {
            name: _FileRecord(path, self._hash_files)
            for name, path in (outputs or {}).items()
        }

        # inspect all declared inputs
        missing_inputs = {}
        for name, input in self._inputs.items():
            input.inspect()
            if not input.exists:
                missing_inputs[name] = input.path

        if missing_inputs:
            raise FileNotFoundError(f"Missing input files: {missing_inputs}")

        # If these things have passed:
        #   serialization of the provided config
        #   existence of required inputs
        #   non-existence of a previous record
        # then we can safely initialize the record directory and write the initial files.
        self.status: RecordStatus = "running"
        self._error: dict[str, str] | None = None

        # Create the record directory and write the config file only AFTER all verification
        self.directory.mkdir(parents=True, exist_ok=True)

        save_config(
            config,
            self._config_file,
            force_replace=force_replace,
        )

        self._config_digest = (
            hash_file(self._config_file)["sha256"] if self._hash_files else None
        )

        self._save_provenance()

    def _as_dict(self) -> ProvenancePayload:
        provenance: ProvenancePayload = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "entry": self._time_entry,
            "exit": self._time_exit,
            "duration_seconds": self._duration,
            "status": self.status,
            "config": {"path": str(self._config_file), "sha256": self._config_digest},
            "git": self._git_info,
            "inputs": {name: input.as_dict() for name, input in self._inputs.items()},
            "outputs": {
                name: output.as_dict() for name, output in self._outputs.items()
            },
            "annotations": self.annotations,
        }

        if self._error is not None:
            provenance["error"] = self._error

        return provenance

    def _save_provenance(self) -> None:
        # Write to a temporary file first to avoid partial writes, then atomically replace with the final file
        temp_file_name = PROVENANCE_FILE_NAME + ".tmp"
        temp_file = self.directory / temp_file_name
        temp_file.write_text(
            json.dumps(self._as_dict(), indent=4) + "\n",
            encoding="utf-8",
        )
        temp_file.replace(self._provenance_file)

    def _ensure_running(self) -> None:
        if self.status != "running":
            raise RuntimeError(f"Cannot modify a record with status '{self.status}'.")

    def add_input(self, name: str, path: PathArg) -> None:
        """
        Register and immediately inspect an input file.

        The file must already exist. Its size and, by default, SHA-256 digest are
        written to the provenance record immediately.

        Entire directories are not supported as inputs.

        Args:
            name: Unique user label used for the input in ``provenance.json``.
            path: Path to an existing regular file.

        Raises:
            RuntimeError: If the record is no longer running.
            ValueError: If ``name`` is already registered or ``path`` is not a
                regular file.
            FileNotFoundError: If ``path`` does not exist.
        """
        self._ensure_running()

        # check if already recorded
        if name in self._inputs:
            raise ValueError(f"Input '{name}' already registered.")

        # declare the input
        input = _FileRecord(path, self._hash_files)
        # inspect it
        input.inspect()
        if not input.exists:
            raise FileNotFoundError(f"Input file '{input.path}' does not exist.")

        # only append when existence is verified
        self._inputs[name] = input

        # update the written record
        self._save_provenance()

    def add_output(self, name: str, path: PathArg) -> None:
        """
        Declare an output that must exist when the record is finished.

        The output does not need to exist yet. It is inspected at ``finish()``.

        Args:
            name: Unique user label used for the output in ``provenance.json``.
            path: Expected path of the output file.

        Raises:
            RuntimeError: If the record is no longer running.
            ValueError: If ``name`` is already registered.
        """
        self._ensure_running()

        # check if already recorded
        if name in self._outputs:
            raise ValueError(f"Output '{name}' already registered.")

        # declare the output
        self._outputs[name] = _FileRecord(path, self._hash_files)

        # update the written record
        self._save_provenance()

    def add_annotations(self, annotations: Mapping[str, Any]) -> None:
        """
        Add arbitrary user annotations to the record.

        Annotations are stored in ``provenance.json`` and can be used for any
        purpose. They are not inspected or validated by the provenance library.

        The provided annotations are concatenated with any existing annotations.
        If a key already exists, its value is overwritten.

        Args:
            annotations: Key-value pairs to add to the record.
        """
        self._ensure_running()

        self.annotations.update(annotations)
        self._save_provenance()

    def _terminate(self) -> None:
        self._time_exit = get_utc_now()
        self._duration = get_duration(self._time_entry, self._time_exit)

    def finish(
        self,
    ) -> None:
        """
        Inspect declared outputs and finalize the record.

        Sets the status to ``"finished"`` if every output exists. If an output
        is missing, the status is set to ``"incomplete"`` and the error is saved
        before an exception is raised.

        Raises:
            RuntimeError: If the record is no longer running.
            FileNotFoundError: If one or more declared outputs are missing.
            ValueError: If an output is not a regular file or changes while being
                hashed.
        """
        self._ensure_running()

        # catch exceptions at inspection to be able to commit the record before re-raising
        try:
            for output in self._outputs.values():
                output.inspect()
        except Exception as exception:
            self.fail(exception)
            raise

        self._terminate()

        # collect potential missing outputs
        missing_outputs = {
            name: output.path
            for name, output in self._outputs.items()
            if not output.exists
        }

        if missing_outputs:
            message = f"Missing expected outputs: {missing_outputs}"
            self.status = "incomplete"
            self._error = {
                "type": "MissingOutputs",
                "message": message,
            }
            self._save_provenance()
            raise FileNotFoundError(message)
        else:
            self.status = "finished"
            self._save_provenance()

    def fail(self, exception=None) -> None:
        """
        Finalize the record with status ``"failed"``.

        Args:
            exception: Optional exception whose type and message should be stored
                in ``provenance.json``.

        Raises:
            RuntimeError: If the record is no longer running.
        """
        self._ensure_running()
        self._terminate()

        self.status = "failed"

        if exception is not None:
            self._error = {
                "type": type(exception).__name__,
                "message": str(exception),
            }

        self._save_provenance()

    # Context manager support for the Record class, i.e. automatic cleanup without explicit finish/fail calls.

    def __enter__(self) -> Record:
        self._ensure_running()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if self.status == "running":
            if exception_type is None:
                self.finish()
            else:
                self.fail(exception_value)

        return False  # do not suppress exceptions, let them propagate to the caller


def start_record(
    config: BaseModel,
    *,
    directory: PathArg,  # target directory for the record
    inputs: Mapping[str, PathArg] | None = None,
    outputs: Mapping[str, PathArg] | None = None,
    annotations: Mapping[str, Any] | None = None,
    hash_files: bool = True,
    force_replace: bool = False,
    git_root: PathArg | None = None,
) -> Record:
    """
    Start a provenance record and write its initial files.

    The configuration is serialized to ``config.json``. Input files are checked
    immediately, and the Git commit, branch, and working-tree state are captured.
    Declared outputs are checked only when the record is finished.

    Use this function as a context manager whenever possible, i.e. in a ``with`` block.

    Args:
        config: Validated Pydantic configuration to store with the run.
        directory: Directory in which to create ``config.json`` and
            ``provenance.json``.
        inputs: Labels mapped to existing input file paths.
        outputs: Labels mapped to expected output file paths. These files may be
            created during the run.
        annotations: Arbitrary key-value pairs to store in the record.
        hash_files: Compute SHA-256 digests for inputs and outputs. File sizes
            are recorded even when this is false.
        force_replace: Replace an existing ``config.json`` or
            ``provenance.json`` in ``directory``. Other files are left untouched.
        git_root: Directory whose Git repository should be inspected. Defaults
            to the current working directory. Git fields are null when no
            repository can be inspected.

    Returns:
        A running ``Record``.

    Raises:
        FileExistsError: If a record already exists and ``force_replace`` is
            false (default).
        FileNotFoundError: If a declared input does not exist.
        ValueError: If a declared input is not a regular file or changes while
            being hashed.
        OSError: If the record directory or files cannot be written.

    Example:
        >>> output = Path("results/summary.csv")
        >>> with start_record(
        ...     config,
        ...     directory="runs/experiment-001",
        ...     inputs={"observations": "data/observations.csv"},
        ...     outputs={"summary": output},
        ... ) as record:
        ...     create_summary(output)
    """
    return Record(
        config,
        directory=directory,
        inputs=inputs,
        outputs=outputs,
        annotations=annotations,
        hash_files=hash_files,
        force_replace=force_replace,
        git_root=git_root,
    )
