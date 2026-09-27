"""Environment-based runtime configuration."""

import os
from dataclasses import dataclass
from pathlib import Path

DATA_PATH_ENV = "TODO_DATA_PATH"
DEFAULT_DATA_PATH = Path("data") / "todos.json"


@dataclass(frozen=True)
class Settings:
    """Runtime settings for one application instance."""

    data_path: Path


def load_settings() -> Settings:
    """Read settings from the environment.

    ``TODO_DATA_PATH`` selects the JSON data file; when it is unset or blank the default is
    ``./data/todos.json``. Relative paths resolve from the process working directory. Nothing is
    created on disk here.
    """
    raw_path = os.environ.get(DATA_PATH_ENV, "").strip()
    return Settings(data_path=Path(raw_path) if raw_path else DEFAULT_DATA_PATH)
