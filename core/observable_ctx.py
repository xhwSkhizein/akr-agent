from typing import Any, Dict, Optional
import logging
logger = logging.getLogger(__name__)

from config.agent_config import AgentConfig
from core.event_bus import EventBus
from core.context import Context

class ObservableCtx:
    def __init__(self, config: AgentConfig, event_bus: EventBus):
        self._data: Context = Context()
        self._event_bus = event_bus
        # 预先加载 system_prompt 到上下文
        self._data.set("system_prompt", config.system_prompt)
        # TODO: 预先加载其他配置

    async def set(self, key: str, value: Any) -> None:
        old_value = self._data.get(key)
        self._data.set(key, value)
        logger.debug(f"Ctx set: key='{key}', value='{value}'")
        # Publish an event that the context has changed
        # The event data should be enough for subscribers to act
        await self._event_bus.publish(event_type="ctx_changed", key=key, value=value, old_value=old_value)

    async def append(self, key: str, value: Any) -> None:
        old_value = self._data.get(key)
        if old_value is None:
            old_value = []
        if not isinstance(old_value, list):
            raise ValueError(f"Key '{key}' is not a list. Cannot append to non-list value.")
        old_value.append(value)
        self._data.set(key, old_value)
        logger.info(f"Ctx append: key='{key}', value='{value}'")
        # Publish an event that the context has changed
        await self._event_bus.publish(event_type="ctx_changed", key=key, value=value, old_value=old_value)

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
        logger.warning(f"Direct assignment to ObservableCtx key '{key}'. Event not published. Use await ctx.set().")
        self._data.set(key, value)
