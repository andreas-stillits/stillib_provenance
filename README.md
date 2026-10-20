# stillib_provenance - a python utility for config and provenance management build on Pydantic 2

## Why does this exist?
The purpose of this utility is not to re-invent Pydantic. Rather, it offers standardization, ease of use, and sensible defaults in a scientific research context. The primary value comes from:
- Nudging towards a centralized `config.py` file rather than scattered and un-documented parameter values.
- A `config.py` template with sensible defaults and quick-start examples
- A minimal I/O library for loading, updating, and documenting configurations

## Installation

### Using PIP
Clone this repository and navigate to the designated location. Activate the virtual environment where you wish to install the utility, then run:
```bash
pip install -e .
```
**_Alternatively:_**

### Add `stillib_provenance` as a dependency of your project
If your project contains a `pyproject.toml` file, you can add the utility under the project/dependency field:
```TOML
# your pyproject.toml

[project]
# other settings ...
dependencies = [
    "stillib_provenance" @ git+https://github.com/andreas-stillits/stillib_provenance.git@<RELEASE_TAG>
]
```
And set `<RELEASE_TAG>` to your desired version.

## Quick Start

1. Add the `config.py` template to your project. Either in the terminal using:
    ```bash
    stillib_provenance init <DESTINATION>
    ```
    or in a Jupyter notebook or python file using:
    ```python
    from stillib_provenance import init_config

    init_config("<DESTINATION>") # run only once at project start
    ```
2. Modify the template to fit your project - i.e. define Config models off of Pydantic's `BaseModel`.
    
    **Then interact with the config using the following 3 operations:**
3. **Instantiate** a config object using `load_config`:
    ```python
    from config import Config
    from stillib_provenance import load_config

    config = load_config(
        Config, # a config model defined in your project's config.py
        source="configs/example.json", # optional JSON file overrides
        field = ..., # optional python overrides using keyword arguments
        ...
    )

    # access config parameters
    result = simulate(config.diffusivity, config.n_steps, ...)
    ```
    *(Values are resolved according to the hiearchy: DEFAULTS -> JSON -> PYTHON OVERRIDES)*
4. **Update** a config with validation during a run using `update_config`:
    ```python
    new_config = update_config(
        config,
        field = ..., 
        ...
    )
    ```
    *(configs are otherwise immutable by convention.)*
5. **Write** a config to a re-loadable JSON file using `dump_config`:
    ```python
    dump_config(
        config,
        "<DESTINATION>"
    )
    ```
    *(Path management should be owned by a dedicated project `paths.py` file - consider [stillib_paths](https://github.com/andreas-stillits/stillib_paths) as a handy utility. `dump_config` will override existing files and raise an error if the parent directory is missing.)*