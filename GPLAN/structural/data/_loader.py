"""YAML table loader for structural/data.

Tables are read once and cached; callers must treat the returned mapping as
read-only (it is the shared cache entry, not a copy). A missing table raises
FileNotFoundError naming the candidate path, never a silent empty dict.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List

import yaml

DATA_DIR = os.path.dirname(os.path.abspath(__file__))


def data_path(name: str) -> str:
    """Absolute path of a data table, with or without the .yaml suffix."""
    stem = str(name)
    for suffix in (".yaml", ".yml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return os.path.join(DATA_DIR, stem + ".yaml")


def load_yaml(name: str) -> Any:
    """Parsed contents of structural/data/<name>.yaml, cached per resolved path."""
    return _load_path(data_path(name))


@lru_cache(maxsize=None)
def _load_path(path: str) -> Any:
    if not os.path.isfile(path):
        raise FileNotFoundError("structural data table not found: " + path)
    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return {} if loaded is None else loaded


def require_keys(d: Dict[str, Any], keys: Iterable[str], table_name: str) -> None:
    """Raise ValueError naming every key `table_name` is missing."""
    if not isinstance(d, dict):
        raise ValueError(table_name + " must be a mapping, got " + type(d).__name__)
    missing = sorted(str(key) for key in keys if key not in d)
    if missing:
        raise ValueError(table_name + " is missing required keys: " + ", ".join(missing))


def available_tables() -> List[str]:
    """Table names present in structural/data, sorted."""
    if not os.path.isdir(DATA_DIR):
        return []
    names = [f[:-5] for f in os.listdir(DATA_DIR) if f.endswith(".yaml")]
    return sorted(names)


def clear_cache() -> None:
    """Drop the table cache (tests that write temporary tables)."""
    _load_path.cache_clear()
