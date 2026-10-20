from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


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


def load_config[ConfigType: BaseModel](
    ConfigModel: type[ConfigType], source: str | Path | None = None, **overrides: Any
) -> ConfigType:
    """
    Load a configuration model according to the hierarchy: defaults -> provided .json file -> python overrides.

    Arguments:
        ConfigModel: The Pydantic BaseModel class to be instantiated.
        source: The path to a JSON file containing the configuration, or None to use defaults.
        **overrides: Keyword arguments representing the fields to be overridden and their new values.

    Returns:
        An instance of the specified configuration model, validated against the model's schema.
    """
    values: dict[str, Any] = {}

    if source is not None:
        source_path = Path(source)
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
    )  # supplies default values not present in JSON source or overrides


def update_config[ConfigType: BaseModel](
    config: ConfigType, **overrides: Any
) -> ConfigType:
    """
    Update selected fields of a configuration model and re-validate it.

    Arguments:
        config: A validated Pydantic BaseModel instance to be updated.
        overrides: Keyword arguments representing the fields to be updated and their new values.

    Returns:
        A new instance of the same configuration model with the updated values, validated against the model's schema.
    """

    values = config.model_dump(
        mode="python",  # maintain python types rather than JSON. E.g., preserve PosixPath('data/mesh.msh') not "data/mesh.msh"
        round_trip=True,  # representation suited for re-validation
        warnings="error",  # serialization warnings -> exceptions
    )
    values = _deep_update(values, overrides)
    return type(config).model_validate(values)


def dump_config(config: BaseModel, path: str | Path) -> Path:
    """
    Dump a validated configuration model to a JSON file.
    Warning: existing files are replaced and parent directories required to exist.

    Arguments:
        config: A validated Pydantic BaseModel instance to be serialized.
        path: The file path where the configuration should be dumped. Can be a string or a Path object.

    Returns:
        The Path object representing the file path where the configuration was dumped.
    """
    path = Path(path)
    # serialize for json with indentation and without aliasing, suitable for re-validation
    payload = config.model_dump_json(
        indent=4,
        round_trip=True,  # representation suited for re-validation
        warnings="error",  # serialization warnings -> exceptions
    )

    path.write_text(payload + "\n", encoding="utf-8")

    return path
