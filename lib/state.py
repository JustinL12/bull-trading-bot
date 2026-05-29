"""File-based state persistence with cross-platform locking."""

import json
import os
from pathlib import Path
from typing import Any

import portalocker

DATA_DIR = Path(__file__).parent.parent / "data"


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else DATA_DIR / p


def read_json(path: str | Path, default: Any = None) -> Any:
    p = _resolve(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_SH)
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default
        finally:
            portalocker.unlock(f)


def write_json(path: str | Path, data: Any, indent: int = 2) -> None:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        try:
            json.dump(data, f, indent=indent, default=str)
        finally:
            portalocker.unlock(f)


def append_jsonl(path: str | Path, record: dict) -> None:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_EX)
        try:
            f.write(json.dumps(record, default=str) + "\n")
        finally:
            portalocker.unlock(f)


def read_jsonl(path: str | Path) -> list[dict]:
    p = _resolve(path)
    if not p.exists():
        return []
    records = []
    with open(p, "r", encoding="utf-8") as f:
        portalocker.lock(f, portalocker.LOCK_SH)
        try:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        finally:
            portalocker.unlock(f)
    return records


def flag_exists(name: str) -> bool:
    return (DATA_DIR / name).exists()


def set_flag(name: str) -> None:
    (DATA_DIR / name).touch()


def clear_flag(name: str) -> None:
    p = DATA_DIR / name
    if p.exists():
        p.unlink()
