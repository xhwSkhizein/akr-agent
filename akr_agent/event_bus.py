from typing import Deque, List, Dict, Any, Callable
from pydantic import BaseModel
import asyncio
import enum
import logging
import threading


class EventType(str, enum.Enum):
    USER_MESSAGE = "user_message"  # User input
    TOOL_CALL = "tool_call"  # ToolCall
    TOOL_RESULT = "tool_result"  # ToolResult
    TOKEN_USAGE = "token_usage"  # Token usage
    AGENT_RESPONSE = "agent_response"  # AgentResponse
    CONTEXT_CHANGED = "context_changed"  # Internal system-triggered context change
    NEW_RULE_GENERATED = "new_rule_generated"  # New rule generated
    RULE_TASK_EXECUTING = "rule_task_executing"  # RuleTask is executing
    RULE_TASK_COMPLETED = "rule_task_completed"  # RuleTask completed
    RULE_TASK_FAILED = "rule_task_failed"  # RuleTask failed
    RULE_TASK_CANCELLED = "rule_task_cancelled"  # RuleTask cancelled


class RealTimeEvent(BaseModel):
    type: EventType
    data: Dict[str, Any]


class EventBus:
    """
    Event bus for internal event passing within Agent
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._queue = asyncio.Queue()
        # Event subscribers mapping: event type -> callback function list
        self._subscribers: Dict[EventType, List[Callable[..., Any]]] = {}
        # Event history: event type -> recent event data queue
        self._event_history: Dict[EventType, Deque] = {}

        # Event type lock mapping: event type -> lock
        self._event_locks: Dict[EventType, threading.Lock] = {}
        # Dictionary lock, used to protect the modification of _subscribers and _event_history dictionaries
        self._dict_lock = threading.Lock()

    def _get_event_lock(self, event_type: EventType) -> threading.Lock:
        """
        Get the lock corresponding to the event type, create if it does not exist

        Args:
            event_type: Event type

        Returns:
            Lock corresponding to the event type
        """
        with self._dict_lock:
            if event_type not in self._event_locks:
                self._event_locks[event_type] = threading.Lock()
            return self._event_locks[event_type]

    def emit(self, event: RealTimeEvent):
        """
        Emit an event
        """
        self._logger.debug(f"Received event {event.type}, data {event.model_dump()}")
        self._queue.put_nowait(event)
        # Record event history
        subscribers = []
        event_lock = self._get_event_lock(event.type)
        with event_lock:
            if event.type not in self._event_history:
                self._event_history[event.type] = Deque(maxlen=1024)
            self._event_history[event.type].append(event.model_dump())
            subscribers = self._subscribers.get(event.type, [])
        # Send event to subscribers
        for callback in subscribers:
            self._logger.debug(f"Event {event.type} sent to subscriber {callback.__name__}")
            asyncio.create_task(callback(event))

    def subscribe(
        self, event_type: EventType, callback: Callable[[RealTimeEvent], None]
    ):
        """
        Subscribe to an event
        """
        self._logger.debug(f"Received event subscription {event_type}, callback {callback.__name__}")
        event_lock = self._get_event_lock(event_type)
        with event_lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(
        self, event_type: EventType, callback: Callable[[RealTimeEvent], None]
    ):
        """
        Unsubscribe from an event
        """
        self._logger.debug(
            f"Received event unsubscription {event_type}, callback {callback.__name__}"
        )
        event_lock = self._get_event_lock(event_type)
        with event_lock:
            if event_type not in self._subscribers:
                self._logger.debug(f"Event {event_type} has no subscribers, unsubscribe failed")
            else:
                self._subscribers[event_type].remove(callback)
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
                    self._logger.debug(f"Event {event_type} has no subscribers, cleaned up")
