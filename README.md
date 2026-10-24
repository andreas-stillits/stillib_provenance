# stillib_provenance - a python utility for config and provenance management build on Pydantic 2

## Why does this exist?
The purpose of this utility is not to re-invent Pydantic. Rather, it aims to offer sensible conventions that fit ergonomically into any scientific python workflow.
The primary value comes from:
- Nudging towards a centralized `config.py` file rather than scattered and un-documented parameter values.
- A minimally invasive `Record` context manager that offers persistence of:
    - Re-loadable config.json for reproducibility
    - Input/Output paths and identities (SHA256 hashing)
    - Git state (commit hash, branch, uncommited changes)
    - Timestamps
  In a provenance.json file.


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

## Quick Start - Config

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
    
3. **Then interact with the config using the following 3 operations:**
    - **Instantiate** a config object using `load_config`:
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

    - **Update** a config with validation during a run using `update_config`:
        ```python
        new_config = update_config(
            config,
            field = ..., 
            ...
        )
        ```
        *(configs are otherwise immutable by convention.)*

    - **Write** a config to a re-loadable JSON file using `dump_config`:
        ```python
        dump_config(
            config,
            "<DESTINATION>"
        )
        ```
        *(Path management should be owned by a dedicated project `paths.py` file - consider [stillib_paths](https://github.com/andreas-stillits/stillib_paths) as a handy utility. `dump_config` will override existing files and raise an error if the parent directory is missing.)*


## Quick Start - Record Manual Clean Up (Jupyter notebooks)

```python
# import your own code
from .project import ...


# ----------------------------------------
# Provenance setup

# import the utility and your config
from .config import Config
from stillib_provenance import load_config, start_record

# instantiate a config - here with default content declared in config.py
config = load_config(Config)

# start a Record: declare input paths, optionally intended output paths - otherwise add later, and your git root if that is not your working directory
record = start_record(
    config,
    directory = "path/to/target/directory",  # where config.json and provenance.json will appear
    inputs = {"name": "path/to/input", ...}
    git_root = "path/to/your/project/code/root",
)
# At this point, stillib has:
#   verified that the config is serializable and written it to config.json
#   verified that the required inputs exist and computed their SHA256 hash
#   inspected the git state and recorded git commit, branch name, and any uncommitted changes
#   recorded a timestamp
# ----------------------------------------

# now run your program like usually

# whenever you generate an output, declare it in the record if you didnt at the beginning
# (you can also add inputs later on - stillib will verify existence and compute a SHA256 checksum)

output = some_function(some_data, some_parameters)
record.add_output("name", "path/to/output")

# when your program is done, finish the record

record.finish() # stillib will now verify declared output existence and compute their SHA256 checksums

```

## Quick Start - Record Manual Automatic Clean Up (Python scripts)

```python
# import your own code
from .project import ...


# import the utility and your config
from .config import Config
from stillib_provenance import load_config, start_record

# instantiate a config - here with default content declared in config.py
config = load_config(Config)

# wrap your program in a record context:

with start_record(
    config,
    directory = "path/to/target/directory",  # where config.json and provenance.json will appear
    inputs = {"name": "path/to/input", ...}
    git_root = "path/to/your/project/code/root",
) as record:

    # have you program in this with-block, e.g.

    output = some_function(some_data, some_parameters)
    record.add_output("name", "path/to/output")

# Once exiting the with-block, stillib will automatically call record.finish() or record.fail() respectively 
```
