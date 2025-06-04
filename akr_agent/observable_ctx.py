from typing import Any, Dict, Optional
import logging
import json

from .utils import get_nested, set_nested
from .event_bus import EventBus, EventType, RealTimeEvent


class Context:
    def __init__(self):
        self._storage: Dict[str, Any] = {}

    def set(self, key: str, value: Any):
        try:
            value = json.loads(value, strict=False)
        except:
            pass
        set_nested(self._storage, key, value)

    def append(self, key: str, value: Any):
        old_value = self.get(key)
        if old_value is None:
            old_value = []
        if not isinstance(old_value, list):
            raise ValueError(
                f"Key '{key}' is not a list. Cannot append to non-list value."
            )
        old_value.append(value)
        self.set(key, old_value)
        logger.debug(f"Ctx append: key='{key}', value='{value}'")

    def get(self, key: str) -> Any:
        return get_nested(self._storage, key)

    def has(self, key: str) -> bool:
        return get_nested(self._storage, key) is not None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._storage)


class ObservableCtx:

    def __init__(self, event_bus: EventBus, logger: logging.Logger):
        self._event_bus: EventBus = event_bus
        self._logger: logging.Logger = logger
        self._data: Context = Context()

    def set(self, key: str, value: Any) -> None:
        old_value = self._data.get(key)
        self._data.set(key, value)
        self._logger.info(
            f"Ctx set: key='{key}', value='{value}', old_value='{old_value}'"
        )
        self._event_bus.emit(
            RealTimeEvent(
                type=EventType.CONTEXT_CHANGED,
                data={"key": key, "value": value, "old_value": old_value},
            )
        )

    def append(self, key: str, value: Any) -> None:
        old_value = self._data.get(key)
        if old_value is None:
            old_value = []
        if not isinstance(old_value, list):
            raise ValueError(
                f"Key '{key}' is not a list. Cannot append to non-list value."
            )
        new_value = old_value.copy()
        new_value.append(value)
        self._data.set(key, new_value)
        self._logger.info(
            f"Ctx append: key='{key}', value='{new_value}', old_value='{old_value}'"
        )
        self._event_bus.emit(
            RealTimeEvent(
                type=EventType.CONTEXT_CHANGED,
                data={"key": key, "value": new_value, "old_value": old_value},
            )
        )

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        value = self._data.get(key)
        if value is None:
            return default
        return value

    def to_dict(self) -> Dict[str, Any]:
        return self._data.to_dict()

    def __contains__(self, key: str) -> bool:
        return self._data.has(key=key)

    def __getitem__(self, key: str) -> Any:
        return self._data.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        # This doesn't publish event, use set() for that
        # For direct dict-like assignment if needed, but prefer set()
        # To make it publish, call self.set() here, but be mindful of async context
        # For simplicity, direct assignment won't publish. Use `await ctx.set()`
        self._logger.warning(
            f"Direct assignment to ObservableCtx key '{key}'. Event not published. Use await ctx.set()."
        )
        self._data.set(key, value)
