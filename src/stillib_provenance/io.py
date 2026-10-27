from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PathArg = str | PathLike[str]


def _deep_update(base: dict, updates: dict) -> dict:
    """
    Helper function to recursively update a dictionary with another dictionary, merging nested dictionaries instead of overwriting them.
    OBS: the implementation does not deep copy non-dictionary objects. As such mutable objects like a list can still be shared between the base and update

    Arguments:
        base: The original dictionary to be updated.
        updates: The dictionary containing (partial) updates to be applied to the base dictionary.

    Returns:
        A new dictionary that is the result of applying the updates to the base dictionary.
    """
    result = dict(base)

    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_update(result[key], value)
        else:
            result[key] = value
    return result


def resolve_path(path: PathArg) -> Path:
    return Path(path).expanduser().resolve()


def load_config[ConfigType: BaseModel](
    ConfigModel: type[ConfigType], source: PathArg | None = None, **overrides: Any
) -> ConfigType:
    """
    Create a validated configuration from model defaults, JSON, and keyword overrides.

    Values are applied in increasing priority: defaults declared by
    ``ConfigModel``, values from ``source``, and finally keyword overrides.
    Nested dictionaries are merged recursively instead of being replaced
    entirely.

    Args:
        ConfigModel: The Pydantic model class to instantiate.
        source: A JSON file containing an object of configuration values.
            If omitted, only model defaults and keyword overrides are used.
            Relative paths are resolved from the current working directory.
        **overrides: Configuration values with the highest priority.

    Returns:
        A validated instance of ``ConfigModel``.

    Raises:
        FileNotFoundError: If ``source`` is provided but does not exist.
        json.JSONDecodeError: If ``source`` is not valid JSON.
        ValueError: If the JSON document is not an object.
        pydantic.ValidationError: If the merged values do not satisfy the declared model.

    Example:
        >>> config = load_config(
        ...     Config,
        ...     source="configs/experiment.json",
        ...     n_steps=2000,
        ... )
    """
    values: dict[str, Any] = {}

    if source is not None:
        source_path = resolve_path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {source_path}")

        with source_path.open("r", encoding="utf-8") as file:
            values = json.load(file)

        if not isinstance(values, dict):
            raise ValueError(
                f"Configuration file must contain a JSON object, got: {type(values).__name__}"
            )

    values = _deep_update(values, overrides)

    return ConfigModel.model_validate(
        values
    )  # supplies default values not present in the JSON source or overrides


def update_config[ConfigType: BaseModel](
    config: ConfigType, **overrides: Any
) -> ConfigType:
    """
    Return a validated copy of a configuration with selected values changed.

    The original model is not modified. Nested dictionaries are merged
    recursively; other values are replaced.

    Args:
        config: The validated Pydantic model to copy.
        **overrides: Values to apply to the copied configuration.

    Returns:
        A new instance of the same model type.

    Raises:
        pydantic.ValidationError: If the updated values do not satisfy the model.

    Example:
        >>> updated = update_config(config, n_steps=2000)
        >>> updated is config
        False
    """

    values = config.model_dump(
        mode="python",  # maintain python types rather than JSON. E.g., preserve PosixPath('data/mesh.msh') not "data/mesh.msh"
        round_trip=True,  # representation suited for re-validation
        warnings="error",  # serialization warnings raised as exceptions
    )
    values = _deep_update(values, overrides)
    return type(config).model_validate(values)


def save_config(config: BaseModel, path: PathArg, force_replace: bool = False) -> Path:
    """
    Write a validated configuration to a re-loadable JSON file.

    Existing files are not replaced by default. Parent directories are not created.

    Args:
        config: The Pydantic model to serialize.
        path: Destination path for the JSON file. Relative paths are resolved from the
            current working directory.
        force_replace: If True, existing files will be overwritten.

    Returns:
        The resolved absolute path of the written file.

    Raises:
        FileNotFoundError: If the destination's parent directory does not exist.
        FileExistsError: If the destination already exists and ``force_replace`` is False.
        OSError: If the destination cannot be written.
        pydantic.PydanticSerializationError: If a field cannot be serialized.

    Example:
        >>> save_config(config, "configs/experiment.json")
        PosixPath("/project/configs/experiment.json")
    """
    path = resolve_path(path)

    # serialize for json with indentation and without aliasing, suitable for re-validation
    # raise serialization error before opening the file to avoid creating an empty file on failure
    payload = config.model_dump_json(
        indent=4,
        round_trip=True,  # representation suited for re-validation
        warnings="error",  # serialization warnings -> exceptions
    )

    mode = "w" if force_replace else "x"
    try:
        with path.open(mode, encoding="utf-8") as file:
            file.write(payload + "\n")
    except FileExistsError as exc:
        raise FileExistsError(
            f"Configuration file already exists: {path}. Use force_replace=True to overwrite."
        ) from exc

    return path
