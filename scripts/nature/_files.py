"""Shared file helpers for the nature scripts."""

import json
import os
from pathlib import Path


def read_json_list(path: Path) -> list:
    """Read a JSON array; a missing file is an empty list."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name}: top level must be an array")
    return data


def write_json_atomic(path: Path, data) -> None:
    """Write JSON to a temp file, then replace the target."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
