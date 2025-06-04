import logging
import time
from typing import Callable, Optional
import asyncio
from .event_bus import EventBus, RealTimeEvent, EventType
from .observable_ctx import ObservableCtx
from .llm.llm_base import (
    GeneralContentBlock,
    TextPrompt,
    ToolCall,
    ToolResult,
    TextResult,
    TokenUsage,
)
from .task_state import TaskState, TaskInfo
from .rule_config import RuleConfig


class ContextManager:

    def __init__(self, logger: logging.Logger):
        self._event_bus = EventBus(logger=logger) 
        self._ctx = ObservableCtx(self._event_bus, logger) 
        self._message_history = asyncio.PriorityQueue()
        self._logger = logger

    def get_context(self) -> ObservableCtx:
        return self._ctx

    def get_event_bus(self) -> EventBus:
        return self._event_bus

    def subscribe(
        self, event_type: EventType, callback: Callable[[RealTimeEvent], None]
    ):
        self._logger.info(f"Subscribe to event {event_type}, callback {callback.__name__}")
        self._event_bus.subscribe(event_type, callback)

    def set_system_prompt(self, system_prompt: str):
        self._ctx.set("system_prompt", system_prompt)

    def emit_event(self, event: RealTimeEvent):
        self._logger.info(f"Emit event {event.type}, data {event.model_dump()}")
        self._event_bus.emit(event)

    async def emit_and_append_to_history(self, message: GeneralContentBlock):
        """
        Send event and add to message history
        """
        await self._message_history.put((time.time(), message))
        self._ctx.append("dialogue.history", message.to_dict())
        if isinstance(message, TextPrompt):
            self._ctx.set("user_input", message.text)
            self.emit_event(
                RealTimeEvent(type=EventType.USER_MESSAGE, data=message.to_dict())
            )
        elif isinstance(message, ToolCall):
            self.emit_event(
                RealTimeEvent(type=EventType.TOOL_CALL, data=message.to_dict())
            )
        elif isinstance(message, ToolResult):
            self.emit_event(
                RealTimeEvent(type=EventType.TOOL_RESULT, data=message.to_dict())
            )
        elif isinstance(message, TextResult):
            self.emit_event(
                RealTimeEvent(type=EventType.AGENT_RESPONSE, data=message.to_dict())
            )
        elif isinstance(message, TokenUsage):
            self.emit_event(
                RealTimeEvent(type=EventType.TOKEN_USAGE, data=message.to_dict())
            )

    def emit_task_executing(self, task_info: TaskInfo):
        task_info.state = TaskState.EXECUTING
        task_info.updated_at = time.time()
        self.emit_event(
            RealTimeEvent(type=EventType.RULE_TASK_EXECUTING, data=task_info.to_dict())
        )

    def emit_task_cancelled(self, task_info: TaskInfo, error_msg: Optional[str]):
        task_info.state = TaskState.FAILED
        task_info.success = False
        task_info.error = error_msg
        task_info.updated_at = time.time()
        self.emit_event(
            RealTimeEvent(
                type=EventType.RULE_TASK_CANCELLED,
                data=task_info.to_dict(),
            )
        )

    def emit_task_failed(
        self, task_info: TaskInfo, execution_time: float, error_msg: Optional[str]
    ):
        task_info.state = TaskState.FAILED
        task_info.success = False
        task_info.error = error_msg
        task_info.execution_time = execution_time
        task_info.updated_at = time.time()
        self.emit_event(
            RealTimeEvent(
                type=EventType.RULE_TASK_FAILED,
                data=task_info.to_dict(),
            )
        )

    def emit_task_completed(
        self, task_info: TaskInfo, execution_time: float, response_full: Optional[str]
    ):
        task_info.state = TaskState.COMPLETED
        task_info.success = True
        task_info.error = None
        task_info.execution_time = execution_time
        task_info.response_full = response_full
        task_info.updated_at = time.time()
        self.emit_event(
            RealTimeEvent(
                type=EventType.RULE_TASK_COMPLETED,
                data=task_info.to_dict(),
            )
        )

    def emit_task_generate_new_rule(
        self, task_info: TaskInfo, rule_config: RuleConfig, immediate: bool = False
    ):
        self.emit_event(
            RealTimeEvent(
                type=EventType.NEW_RULE_GENERATED,
                data={
                    "task_id": task_info.task_id,
                    "rule_config": rule_config,
                    "immediate": immediate,
                },
            )
        )
