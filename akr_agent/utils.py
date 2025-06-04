from typing import Any, Dict
from pathlib import Path


def get_workspace_root(sid: str) -> Path:
    return Path(f"./akr-agent/{sid}")


def get_container_workspace(sid: str) -> Path:
    return Path(f"./akr-agent/{sid}/container")


def get_nested(data: Dict, keys: str, default: Any = None) -> Any:
    """
    使用点表示法访问嵌套字典键。

    Args:
        data: 要访问的字典
        keys: 点表示法的键路径，如 "a.b.c"
        default: 如果键不存在时返回的默认值

    Returns:
        找到的值或默认值
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
    使用点表示法设置嵌套字典键。

    Args:
        data: 要修改的字典
        keys: 点表示法的键路径，如 "a.b.c"
        value: 要设置的值
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
