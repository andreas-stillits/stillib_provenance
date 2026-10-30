# stillib_provenance - a python utility for config and provenance management built on Pydantic 2

## Why does this exist?
The purpose of this utility is not to re-invent Pydantic. Rather, it aims to offer sensible conventions that fit ergonomically into any scientific python workflow.
The primary value comes from:
- Nudging towards a centralized `config.py` file rather than scattered and un-documented parameter values.
- A minimally invasive `Record` context manager that offers persistence of:
    - Re-loadable config.json for reproducibility
    - Input/Output paths and content identity (SHA256 hashing)
    - Git state (commit hash, branch, uncommited changes)
    - Timestamps

All in a provenance.json file.

**Design Principle:** *Path and execution logic is project owned. What the utility offers is consistent registration.* 


## Installation

### Using PIP
Clone this repository and navigate to the designated location. Activate the virtual environment where you wish to install the utility, then run:
```bash
pip install -e .
```
**_Alternatively:_**

### Add `stillib_provenance` as a dependency of your project
If your project contains a `pyproject.toml` file, you can add the utility under the project dependencies field:
```TOML
# your pyproject.toml

[project]
# other settings ...
dependencies = [
    "stillib_provenance @ git+https://github.com/andreas-stillits/stillib_provenance.git@v0.6.1",
]
```
Different releases can be referenced by modifying the trailing tag.



## Quick Start

The utility offers a `config.py` template you can materialize in your project directory using either:
1. The terminal:
    ```bash
    stillib_provenance init "config.py" 
    ```
2. Python (notebook or .py file):
    ```python
    # in a .ipynb notebook or .py file
    from stillib_provenance import init_config

    init_config("config.py") # run only once at project start
    ```
The above example assumes your working directory to be the target destination. Specify the path if it is not.


### Config Only

Having declared config models in your project's `config.py` using Pydantic's `BaseModel` class, you can load, update, and save it as a re-loadable `config.json` file. Here is a minimal example:
```python
from config import Config
from stillib_provenance import load_config, save_config, update_config

# instantiate a config object
config = load_config(
    Config, # default schema declared in config.py
    source="configs/example.json", # optional JSON file overrides - for instance a previously saved config
    n_steps=200, # optional python overrides using keyword arguments
)

# Access parameters as attributes, i.e. config.n_steps returns '200'

# update a config field with re-validation using keyword arguments
updated = update_config(config, n_steps=500)

# save config as re-loadable JSON, parent directories are not created
save_config(updated, "configs/updated.json", force_replace=True) # raises error on existing files by default
```
During a `load_config` call, values are resolved according to the hierarchy DEFAULTS --> JSON --> KEYWORDS.

### Full Record 
Whenever possible, prioritize to invoke `Record` as a context manager (using a `with`-block) and choose .py files over .ipynb notebooks for stricter reproducibility.

#### Record as a context manager
```python
from config import Config
from stillib_provenance import load_config, start_record

config = load_config(Config)

with start_record(
    config,
    directory = "path/to/target/directory",  # where config.json and provenance.json will be written
    inputs = {"name": "path/to/input", ...},   # declare required input files
    git_root = "path/to/your/project/code/root", # OPTIONAL: leave empty if project root is your working directory
    data_root = "path/to/common/root/of/inputs/and/outputs", # OPTIONAL: eases later portability
) as record:
    # AT ENTRY:
    #   File inspection: existence check on all inputs and SHA256 hashing for content identity
    #   Git inspection: current commit, current branch, uncommitted changes?
    #   The config is serialized and written to disk
    #   A preliminary provenance.json is written to disk
    #   record.status set to "running

    # ----------------------------------------------------------------------
    # YOUR CODE ...
    # ----------------------------------------------------------------------

    # MID RUN OPERATIONS:
    # add inputs dynamically
    record.add_input("name", "path/to/input") # input is immediately inspected, raises error on failure
    # add outputs dynamically
    record.add_output("name", "path/to/output") # outputs are only declared; inspection occurs at exit
    # add arbitrary annotations
    record.add_annotations({"some_key": "some_value"}) # user specified key-value pairs saved in provenance.json
    # all changes are written to the preliminary provenance.json atomically


# AT EXIT:
#   File inspection: existence check on all declared outputs and SHA256 hashing for content identity
#   Status Update:
#       finished: "All declared outputs are present and their hashes computed"
#       incomplete: "Some declared outputs are not present"
#       failed: "An exception occurred and its type and message was in provenance.json, then re-raised; Record does not suppress exceptions"
```

#### Manual Cleanup
The `Record` exposes `Record.finish()` and `Record.fail()` for manual cleanup. This can be handy if your program extends over multiple cells in a .ipynb notebook. However, consider that such a structure weakens the degree of reproducibility promised by the git inspection: a clean tree with a recorded commit hash does not provide information about the order in which cells were executed in a notebook.

```python
from config import Config
from stillib_provenance import load_config, start_record

config = load_config(Config)

record = start_record(
    config,
    directory = "path/to/target/directory",  # where config.json and provenance.json will be written
    inputs = {"name": "path/to/input", ...},   # declare required input files
    git_root = "path/to/your/project/code/root", # leave empty if project root is your working directory
    data_root = "path/to/common/root/of/inputs/and/outputs", # OPTIONAL: eases later portability
)

try:
    # ----------------------------------------------------------------------
    # YOUR CODE ...
    # ----------------------------------------------------------------------
except Exception as exc:
    record.fail(exc) 
    raise # fail() records the exception but does not re-raise. Use raise in the except block explicitly
else:
    record.finish()
```
A simpler implementation is to just put `record.finish()` at the end of your program. However, if any exceptions occur they will not be written to the recorded provenance.json file which will be left on disk with status "running". 

### Example provenance.json - schema-version 3.0

```JSON
{
    "schema_version": "3.0",
    "entry_point": "project/processing.py",
    "entry": "2026-10-28T10:33:59.224520+00:00",
    "exit": "2026-10-28T10:33:59.225701+00:00",
    "duration_seconds": 0.001,
    "status": "finished",
    "config": {
        "path": "/home/user/project/data/run/config.json",
        "sha256": "b909b65cba86269dc53ed6d14c8e459b78af53c9cb48841a996eec98e40fd40a",
    },
    "git": {
        "path": "home/user/project",
        "commit": "1b12dd92e45eb7bf6b2c0a4b8f96ebe025162fab",
        "branch": "main",
        "dirty": false
    },
    "inputs": {
        "signal": {
            "path": "/home/user/project/data/input.txt",
            "exists": true,
            "size_bytes": 9,
            "sha256": "1307990e6ba5ca145eb35e99182a9bec46531bc54ddf656a602c780fa0240dee"
        }
    },
    "outputs": {
        "processed": {
            "path": "/home/user/project/data/run/output.npy",
            "exists": true,
            "size_bytes": 152,
            "sha256": "f9903acaeea88e7642e9820968f19d2c30dabf7aeb913e939bc23dc2f27be854"
        }
    },
    "annotations": {
        "mean": 2.0,
        "std": 1.0
    },
    "data_root": "/home/user/project/data",
}

```
