from typing import Callable, Dict, List, Any, Optional
import logging
import asyncio
import threading
from collections import deque

logger = logging.getLogger(__name__)


class EventType:
    """事件类型常量"""
    # 上下文变化事件
    CTX_CHANGED = "ctx_changed"
    
    # 任务状态变化事件
    TASK_CHANGED = "task_changed"
    
    # 流状态变化事件
    STREAM_CHANGED = "stream_changed"


class ChangeType:
    """变化类型常量，用于细分事件类型"""
    # 任务变化类型
    TASK_CREATED = "created"
    TASK_STATE_CHANGED = "state_changed"
    TASK_COMPLETED = "completed"
    TASK_FAILED = "failed"
    
    # 流变化类型
    STREAM_REGISTERED = "registered"
    STREAM_EXHAUSTED = "exhausted"
    STREAM_ERROR = "error"


class EventBus:
    """线程安全的事件总线，负责事件的发布和订阅

    支持异步事件处理、事件历史记录和错误处理
    使用细粒度锁机制保证线程安全，为不同事件类型使用独立的锁以提高并发性能
    """

    def __init__(self, max_history_size: int = 100):
        # 事件订阅者映射：事件类型 -> 回调函数列表
        self._subscribers: Dict[EventType, List[Callable[..., Any]]] = {}

        # 事件历史记录：事件类型 -> 最近的事件数据队列
        self._event_history: Dict[EventType, deque] = {}

        # 事件类型锁映射：事件类型 -> 锁
        self._event_locks: Dict[EventType, threading.Lock] = {}

        # 字典锁，用于保护 _subscribers 和 _event_history 字典的修改
        self._dict_lock = threading.Lock()

        # 最大历史记录大小
        self._max_history_size = max_history_size

    def _get_event_lock(self, event_type: EventType) -> threading.Lock:
        """获取事件类型对应的锁，如果不存在则创建

        Args:
            event_type: 事件类型

        Returns:
            事件类型对应的锁
        """
        with self._dict_lock:
            if event_type not in self._event_locks:
                self._event_locks[event_type] = threading.Lock()
            return self._event_locks[event_type]

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[..., Any],
        send_last_event: bool = False,
    ) -> None:
        """订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数，接收事件数据字典作为参数
            send_last_event: 是否立即发送最近一次的事件数据给新订阅者
        """
        event_lock = self._get_event_lock(event_type)

        with self._dict_lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []

        with event_lock:
            if callback not in self._subscribers[event_type]:  # 避免重复订阅
                self._subscribers[event_type].append(callback)
                logger.debug(f"回调 {callback.__name__} 已订阅事件 '{event_type}'")

                # 如果需要，发送最近一次的事件数据给新订阅者
                if send_last_event:
                    last_event = self.get_last_event(event_type)
                    if last_event:
                        asyncio.create_task(
                            self._safe_call_callback(callback, event_type, last_event)
                        )
            else:
                logger.debug(f"回调 {callback.__name__} 已经订阅了事件 '{event_type}'")

    def unsubscribe(self, event_type: EventType, callback: Callable[..., Any]) -> None:
        """取消订阅事件

        Args:
            event_type: 事件类型
            callback: 要取消订阅的回调函数
        """
        if event_type not in self._subscribers:
            return

        event_lock = self._get_event_lock(event_type)
        with event_lock:
            if callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)
                logger.debug(f"回调 {callback.__name__} 已取消订阅事件 '{event_type}'")

                # 如果没有订阅者了，删除该事件类型
                if not self._subscribers[event_type]:
                    with self._dict_lock:
                        del self._subscribers[event_type]
                        # 同时删除对应的锁
                        if event_type in self._event_locks:
                            del self._event_locks[event_type]

    async def publish(self, event_type: EventType, **kwargs: Any) -> None:
        """发布事件到所有订阅者

        Args:
            event_type: 事件类型
            **kwargs: 事件数据，将作为字典传递给订阅者
        """
        # 构建事件数据字典
        event_data_dict = kwargs

        # 记录事件历史
        self._record_event_history(event_type, event_data_dict)

        # 获取事件锁
        event_lock = self._get_event_lock(event_type)

        # 如果有订阅者，通知所有订阅者
        with event_lock:
            if event_type in self._subscribers and self._subscribers[event_type]:
                # 创建副本，防止回调中修改订阅列表
                callbacks = list(self._subscribers[event_type])
            else:
                logger.debug(f"事件 '{event_type}' 没有订阅者，事件未发布")
                return

        # 在锁外执行回调，避免长时间持有锁
        failed_callbacks = []
        for callback in callbacks:
            try:
                await self._safe_call_callback(callback, event_type, event_data_dict)
            except Exception as e:
                logger.error(f"事件 '{event_type}' 回调执行失败: {e}", exc_info=True)
                failed_callbacks.append((callback, str(e)))

        # 记录失败的回调
        if failed_callbacks:
            logger.warning(
                f"事件 '{event_type}' 有 {len(failed_callbacks)} 个回调执行失败"
            )

    async def _safe_call_callback(
        self, callback: Callable[..., Any], event_type: str, event_data: Dict[str, Any]
    ) -> None:
        """安全地调用回调函数，处理异常

        Args:
            callback: 回调函数
            event_type: 事件类型，用于日志
            event_data: 事件数据字典
        """
        try:
            await callback(event_data)
        except asyncio.CancelledError:
            # 重新抛出取消异常，允许正确处理任务取消
            raise
        except Exception as e:
            logger.error(
                f"事件 '{event_type}' 回调 {callback.__name__} 执行失败: {e}",
                exc_info=True,
            )
            # 继续执行其他回调，不中断
            raise

    def _record_event_history(
        self, event_type: EventType, event_data: Dict[str, Any]
    ) -> None:
        """记录事件历史

        Args:
            event_type: 事件类型
            event_data: 事件数据字典
        """
        event_lock = self._get_event_lock(event_type)

        with self._dict_lock:
            if event_type not in self._event_history:
                self._event_history[event_type] = deque(maxlen=self._max_history_size)

        # 添加事件数据到历史记录
        with event_lock:
            self._event_history[event_type].append(event_data)

    def get_last_event(self, event_type: EventType) -> Optional[Dict[str, Any]]:
        """获取指定事件类型的最近一次事件数据

        Args:
            event_type: 事件类型

        Returns:
            最近一次事件数据，如果没有则返回 None
        """
        if event_type not in self._event_history:
            return None

        event_lock = self._get_event_lock(event_type)
        with event_lock:
            if self._event_history[event_type]:
                return self._event_history[event_type][-1]
        return None

    def clear_history(self, event_type: Optional[EventType] = None) -> None:
        """清除事件历史记录

        Args:
            event_type: 要清除的事件类型，如果为 None 则清除所有历史记录
        """
        if event_type is None:
            # 清除所有历史记录需要获取所有事件锁
            with self._dict_lock:
                event_types = list(self._event_history.keys())

            # 逐个获取锁并清除历史记录
            for evt_type in event_types:
                event_lock = self._get_event_lock(evt_type)
                with event_lock:
                    if evt_type in self._event_history:
                        self._event_history[evt_type].clear()
        else:
            # 清除单个事件类型的历史记录
            event_lock = self._get_event_lock(event_type)
            with event_lock:
                if event_type in self._event_history:
                    self._event_history[event_type].clear()
