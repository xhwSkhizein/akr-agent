import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from core.event_bus import EventType, EventBus


# 用于为 MagicMock 提供 spec 的辅助函数
async def dummy_callback(event_data):
    pass


class TestEventBus:
    """测试EventBus类"""

    def test_initialization(self):
        """测试初始化"""
        event_bus = EventBus()
        assert event_bus._subscribers == {}
        assert event_bus._event_history == {}
        assert event_bus._max_history_size == 100

        # 测试自定义历史大小
        event_bus = EventBus(max_history_size=50)
        assert event_bus._max_history_size == 50

    def test_subscribe(self):
        """测试订阅事件"""
        event_bus = EventBus()
        # 使用 spec 并添加 __name__ 属性
        callback = MagicMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback)

        # 验证订阅成功
        assert EventType.CTX_CHANGED in event_bus._subscribers
        assert callback in event_bus._subscribers[EventType.CTX_CHANGED]

        # 测试重复订阅
        event_bus.subscribe(EventType.CTX_CHANGED, callback)
        assert len(event_bus._subscribers[EventType.CTX_CHANGED]) == 1  # 不应该重复添加

    @pytest.mark.asyncio
    async def test_subscribe_with_last_event(self):
        """测试订阅事件并接收最近事件"""
        event_bus = EventBus()

        # 记录事件历史
        event_data = {"key": "value"}
        event_bus._record_event_history(EventType.CTX_CHANGED, event_data)

        # 创建异步回调
        callback = AsyncMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"

        # 订阅事件并请求最近事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback, send_last_event=True)

        # 等待异步任务完成
        await asyncio.sleep(0.1)

        # 验证回调被调用，并接收到最近事件
        callback.assert_called_once()
        assert callback.call_args[0][0] == event_data

    def test_unsubscribe(self):
        """测试取消订阅"""
        event_bus = EventBus()
        # 使用 spec 并添加 __name__ 属性
        callback = MagicMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback)
        assert callback in event_bus._subscribers[EventType.CTX_CHANGED]

        # 取消订阅
        event_bus.unsubscribe(EventType.CTX_CHANGED, callback)
        assert (
            EventType.CTX_CHANGED not in event_bus._subscribers
        )  # 应该清除空的事件类型

        # 测试取消不存在的订阅
        event_bus.unsubscribe("non_existent_event", callback)  # 不应该抛出异常

    @pytest.mark.asyncio
    async def test_publish(self):
        """测试发布事件"""
        event_bus = EventBus()

        # 创建异步回调
        callback = AsyncMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback)

        # 发布事件
        await event_bus.publish(EventType.CTX_CHANGED, key="value")

        # 验证回调被调用
        callback.assert_called_once()
        assert callback.call_args[0][0] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_publish_multiple_callbacks(self):
        """测试发布事件到多个回调"""
        event_bus = EventBus()

        # 创建多个异步回调
        callback1 = AsyncMock(spec=dummy_callback)
        callback1.__name__ = "mock_callback1"
        callback2 = AsyncMock(spec=dummy_callback)
        callback2.__name__ = "mock_callback2"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback1)
        event_bus.subscribe(EventType.CTX_CHANGED, callback2)

        # 发布事件
        await event_bus.publish(EventType.CTX_CHANGED, key="value")

        # 验证所有回调都被调用
        callback1.assert_called_once()
        callback2.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self):
        """测试发布没有订阅者的事件"""
        event_bus = EventBus()

        # 发布没有订阅者的事件
        await event_bus.publish("no_subscribers_event", key="value")
        # 不应该抛出异常

    @pytest.mark.asyncio
    async def test_publish_callback_error(self):
        """测试回调执行出错"""
        event_bus = EventBus()

        # 创建会抛出异常的回调
        async def error_callback(event_data):
            raise Exception("测试错误")

        # 创建正常回调
        normal_callback = AsyncMock(spec=dummy_callback)
        normal_callback.__name__ = "mock_callback"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, error_callback)
        event_bus.subscribe(EventType.CTX_CHANGED, normal_callback)

        # 发布事件
        await event_bus.publish(EventType.CTX_CHANGED, key="value")

        # 验证正常回调仍然被调用
        normal_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_cancelled_error(self):
        """测试取消错误"""
        event_bus = EventBus()

        # 创建会抛出取消异常的回调
        async def cancelled_callback(event_data):
            raise asyncio.CancelledError()

        # 创建正常回调
        normal_callback = AsyncMock(spec=dummy_callback)
        normal_callback.__name__ = "mock_callback"

        # 订阅事件
        event_bus.subscribe(EventType.CTX_CHANGED, cancelled_callback)
        event_bus.subscribe(EventType.CTX_CHANGED, normal_callback)

        # 发布事件应该重新抛出取消异常
        with pytest.raises(asyncio.CancelledError):
            await event_bus.publish(EventType.CTX_CHANGED, key="value")

    @pytest.mark.asyncio
    async def test_event_history_recording(self):
        """测试事件历史记录"""
        event_bus = EventBus(max_history_size=3)

        # 发布多个事件
        await event_bus.publish(EventType.CTX_CHANGED, value=1)
        await event_bus.publish(EventType.CTX_CHANGED, value=2)
        await event_bus.publish(EventType.CTX_CHANGED, value=3)

        # 验证事件历史记录
        assert EventType.CTX_CHANGED in event_bus._event_history
        assert len(event_bus._event_history[EventType.CTX_CHANGED]) == 3
        assert event_bus._event_history[EventType.CTX_CHANGED][0] == {"value": 1}
        assert event_bus._event_history[EventType.CTX_CHANGED][1] == {"value": 2}
        assert event_bus._event_history[EventType.CTX_CHANGED][2] == {"value": 3}

        # 测试历史记录大小限制
        await event_bus.publish(EventType.CTX_CHANGED, value=4)
        assert len(event_bus._event_history[EventType.CTX_CHANGED]) == 3
        assert event_bus._event_history[EventType.CTX_CHANGED][0] == {"value": 2}
        assert event_bus._event_history[EventType.CTX_CHANGED][1] == {"value": 3}
        assert event_bus._event_history[EventType.CTX_CHANGED][2] == {"value": 4}

    def test_get_last_event(self):
        """测试获取最近事件"""
        event_bus = EventBus()

        # 没有事件历史时返回 None
        assert event_bus.get_last_event(EventType.CTX_CHANGED) is None

        # 记录事件历史
        event_bus._record_event_history(EventType.CTX_CHANGED, {"value": 1})
        event_bus._record_event_history(EventType.CTX_CHANGED, {"value": 2})

        # 获取最近事件
        last_event = event_bus.get_last_event(EventType.CTX_CHANGED)
        assert last_event == {"value": 2}

    def test_clear_history(self):
        """测试清除事件历史"""
        event_bus = EventBus()

        # 记录多个事件类型的历史
        event_bus._record_event_history("event1", {"value": 1})
        event_bus._record_event_history("event2", {"value": 2})

        # 清除特定事件类型的历史
        event_bus.clear_history("event1")
        assert "event1" in event_bus._event_history
        assert len(event_bus._event_history["event1"]) == 0
        assert len(event_bus._event_history["event2"]) == 1

        # 清除所有事件历史
        event_bus.clear_history()
        assert event_bus._event_history == {}

    @pytest.mark.asyncio
    async def test_event_types_constants(self):
        """测试事件类型常量"""
        event_bus = EventBus()

        # 使用 EventType 常量
        callback = AsyncMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"

        # 订阅使用常量定义的事件
        event_bus.subscribe(EventType.CTX_CHANGED, callback)
        event_bus.subscribe(EventType.TASK_CHANGED, callback)
        event_bus.subscribe(EventType.STREAM_CHANGED, callback)

        # 发布事件
        await event_bus.publish(EventType.CTX_CHANGED, key="ctx")
        await event_bus.publish(EventType.TASK_CHANGED, key="task")
        await event_bus.publish(EventType.STREAM_CHANGED, key="stream")

        # 验证回调被调用了3次
        assert callback.call_count == 3
