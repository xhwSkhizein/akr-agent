from typing import Deque, List, Dict, Any, Callable
from pydantic import BaseModel
import asyncio
import enum
import logging
import threading


class EventType(str, enum.Enum):
    USER_MESSAGE = "user_message"  # 用户输入
    TOOL_CALL = "tool_call"  # ToolCall
    TOOL_RESULT = "tool_result"  # ToolResult
    AGENT_RESPONSE = "agent_response"  # AgentResponse
    CONTEXT_CHANGED = "context_changed"  # 内部系统引发的上下文变更
    NEW_RULE_GENERATED = "new_rule_generated"  # 新规则生成
    RULE_TASK_EXECUTING = "rule_task_executing"  # RuleTask 正在执行
    RULE_TASK_COMPLETED = "rule_task_completed"  # RuleTask 执行完成
    RULE_TASK_FAILED = "rule_task_failed"  # RuleTask 执行失败
    RULE_TASK_CANCELLED = "rule_task_cancelled"  # RuleTask 被取消


class RealTimeEvent(BaseModel):
    type: EventType
    data: Dict[str, Any]


class EventBus:
    """
    事件总线, 用于在 Agent 内部传递事件
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._queue = asyncio.Queue()
        # 事件订阅者映射：事件类型 -> 回调函数列表
        self._subscribers: Dict[EventType, List[Callable[..., Any]]] = {}
        # 事件历史记录：事件类型 -> 最近的事件数据队列
        self._event_history: Dict[EventType, Deque] = {}

        # 事件类型锁映射：事件类型 -> 锁
        self._event_locks: Dict[EventType, threading.Lock] = {}
        # 字典锁，用于保护 _subscribers 和 _event_history 字典的修改
        self._dict_lock = threading.Lock()

    def _get_event_lock(self, event_type: EventType) -> threading.Lock:
        """
        获取事件类型对应的锁，如果不存在则创建

        Args:
            event_type: 事件类型

        Returns:
            事件类型对应的锁
        """
        with self._dict_lock:
            if event_type not in self._event_locks:
                self._event_locks[event_type] = threading.Lock()
            return self._event_locks[event_type]

    def emit(self, event: RealTimeEvent):
        """
        发送事件
        """
        self._logger.debug(f"收到事件 {event.type}， 数据 {event.model_dump()}")
        self._queue.put_nowait(event)
        # 记录事件历史
        subscribers = []
        event_lock = self._get_event_lock(event.type)
        with event_lock:
            if event.type not in self._event_history:
                self._event_history[event.type] = Deque(maxlen=1024)
            self._event_history[event.type].append(event.model_dump())
            subscribers = self._subscribers.get(event.type, [])
        # 发送事件给订阅者
        for callback in subscribers:
            self._logger.debug(f"事件 {event.type} 发送给订阅者 {callback.__name__}")
            asyncio.create_task(callback(event))

    def subscribe(
        self, event_type: EventType, callback: Callable[[RealTimeEvent], None]
    ):
        """
        订阅事件
        """
        self._logger.debug(f"收到事件订阅 {event_type}， 回调函数 {callback.__name__}")
        event_lock = self._get_event_lock(event_type)
        with event_lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(
        self, event_type: EventType, callback: Callable[[RealTimeEvent], None]
    ):
        """
        取消订阅事件
        """
        self._logger.debug(
            f"收到事件取消订阅 {event_type}， 回调函数 {callback.__name__}"
        )
        event_lock = self._get_event_lock(event_type)
        with event_lock:
            if event_type not in self._subscribers:
                self._logger.debug(f"事件 {event_type} 没有订阅者，取消订阅失败")
            else:
                self._subscribers[event_type].remove(callback)
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
                    self._logger.debug(f"事件 {event_type} 没有订阅者，清理")
