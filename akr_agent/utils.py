from typing import Any, Dict
from pathlib import Path


def get_workspace_root(sid: str) -> Path:
    return Path(f"./akr-agent/{sid}")


def get_container_workspace(sid: str) -> Path:
    return Path(f"./akr-agent/{sid}/container")


def get_nested(data: Dict, keys: str, default: Any = None) -> Any:
    """
    Access nested dictionary keys using dot notation.

    Args:
        data: The dictionary to access
        keys: The dot notation key path, e.g. "a.b.c"
        default: The default value to return if the key does not exist

    Returns:
        The value found or the default value
    """
    if not keys:
        return data

    key_list = keys.split(".")
    current = data

    for key in key_list:
        if isinstance(current, dict):
            current = current.get(key, default)
        elif isinstance(current, list):
            try:
                idx = int(key)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            except (ValueError, IndexError):
                return default
        else:
            return default

        if current is default:
            break

    return current


def set_nested(data: Dict, keys: str, value: Any) -> None:
    """
    Set nested dictionary keys using dot notation.

    Args:
        data: The dictionary to modify
        keys: The dot notation key path, e.g. "a.b.c"
        value: The value to set
    """
    if not keys:
        return

    key_list = keys.split(".")
    current = data

    for i, key in enumerate(key_list[:-1]):
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]

    current[key_list[-1]] = value
