import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from core.event_bus import EventBus

# 用于为 MagicMock 提供 spec 的辅助函数
async def dummy_callback(event_data):
    pass


class TestEventBus:
    """测试EventBus类"""

    def test_initialization(self):
        """测试初始化"""
        event_bus = EventBus()
        assert event_bus._subscribers == {}

    def test_subscribe(self):
        """测试订阅事件"""
        event_bus = EventBus()
        # 使用 spec 并添加 __name__ 属性
        callback = MagicMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"
        
        # 订阅事件
        event_bus.subscribe("test_event", callback)
        
        # 验证订阅成功
        assert "test_event" in event_bus._subscribers
        assert callback in event_bus._subscribers["test_event"]
        
        # 测试重复订阅
        event_bus.subscribe("test_event", callback)
        assert len(event_bus._subscribers["test_event"]) == 1  # 不应该重复添加

    def test_unsubscribe(self):
        """测试取消订阅"""
        event_bus = EventBus()
        # 使用 spec 并添加 __name__ 属性
        callback = MagicMock(spec=dummy_callback)
        callback.__name__ = "mock_callback"
        
        # 订阅事件
        event_bus.subscribe("test_event", callback)
        assert callback in event_bus._subscribers["test_event"]
        
        # 取消订阅
        event_bus.unsubscribe("test_event", callback)
        assert "test_event" not in event_bus._subscribers  # 应该清除空的事件类型
        
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
        event_bus.subscribe("test_event", callback)
        
        # 发布事件
        await event_bus.publish("test_event", key="value")
        
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
        event_bus.subscribe("test_event", callback1)
        event_bus.subscribe("test_event", callback2)
        
        # 发布事件
        await event_bus.publish("test_event", key="value")
        
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
        event_bus.subscribe("test_event", error_callback)
        event_bus.subscribe("test_event", normal_callback)
        
        # 发布事件
        await event_bus.publish("test_event", key="value")
        
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
        event_bus.subscribe("test_event", cancelled_callback)
        event_bus.subscribe("test_event", normal_callback)
        
        # 发布事件应该重新抛出取消异常
        with pytest.raises(asyncio.CancelledError):
            await event_bus.publish("test_event", key="value")
