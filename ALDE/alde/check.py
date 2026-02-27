from __future__ import annotations

"""Helper functions for assistant metadata lookups."""

from typing import Any, Dict, List


def _key_values(keys: List[str], data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a list of dicts containing only the requested *keys*."""

    filtered: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return filtered

    for entry in data:
        if not isinstance(entry, dict):
            continue
        chunk: Dict[str, Any] = {}
        for key in keys:
            value = entry.get(key)
            if value not in (None, ""):
                chunk[key] = value
        if chunk:
            filtered.append(chunk)
    return filtered


def check(cls, _value: str, keys: List[str], *, data: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Return the first key-bundle where *_value* matches one of the keys."""

    if not isinstance(keys, list):
        keys = list(keys) if keys is not None else []
    if not isinstance(data, list):
        data = []

    for bundle in _key_values(keys, data):
        if any(bundle.get(key) == _value for key in keys):
            cls._value_name = bundle
            return bundle

    cls._value_name = None
    print(f"No value found for: {_value}!")
    return None
