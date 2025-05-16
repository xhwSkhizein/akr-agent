import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

from core.observable_ctx import ObservableCtx
from core.event_bus import EventBus


class TestObservableCtx:
    """测试ObservableCtx类"""

    def test_initialization(self):
        """测试初始化"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, key1="value1", key2="value2")
        
        # 验证初始值
        assert ctx.get("key1") == "value1"
        assert ctx.get("key2") == "value2"

    @pytest.mark.asyncio
    async def test_set(self):
        """测试设置值"""
        event_bus = EventBus()
        event_callback = AsyncMock()
        event_bus.subscribe("ctx_changed", event_callback)
        
        ctx = ObservableCtx(event_bus=event_bus)
        
        # 设置值
        await ctx.set("test_key", "test_value")
        
        # 验证值已设置
        assert ctx.get("test_key") == "test_value"
        
        # 验证事件已发布
        event_callback.assert_called_once()
        event_data = event_callback.call_args[0][0]
        assert event_data["key"] == "test_key"
        assert event_data["value"] == "test_value"
        assert event_data["old_value"] is None

    @pytest.mark.asyncio
    async def test_set_update_existing(self):
        """测试更新现有值"""
        event_bus = EventBus()
        event_callback = AsyncMock()
        event_bus.subscribe("ctx_changed", event_callback)
        
        ctx = ObservableCtx(event_bus=event_bus, test_key="old_value")
        
        # 更新值
        await ctx.set("test_key", "new_value")
        
        # 验证值已更新
        assert ctx.get("test_key") == "new_value"
        
        # 验证事件已发布
        event_callback.assert_called_once()
        event_data = event_callback.call_args[0][0]
        assert event_data["key"] == "test_key"
        assert event_data["value"] == "new_value"
        assert event_data["old_value"] == "old_value"

    @pytest.mark.asyncio
    async def test_append(self):
        """测试追加到列表"""
        event_bus = EventBus()
        event_callback = AsyncMock()
        event_bus.subscribe("ctx_changed", event_callback)
        
        ctx = ObservableCtx(event_bus=event_bus, test_list=["item1"])
        
        # 追加到列表
        await ctx.append("test_list", "item2")
        
        # 验证值已追加
        assert ctx.get("test_list") == ["item1", "item2"]
        
        # 验证事件已发布
        event_callback.assert_called_once()
        event_data = event_callback.call_args[0][0]
        assert event_data["key"] == "test_list"
        assert event_data["value"] == "item2"
        assert event_data["old_value"] == ["item1", "item2"]  # 注意这里是完整列表

    @pytest.mark.asyncio
    async def test_append_to_non_list(self):
        """测试追加到非列表"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, test_key="not_a_list")
        
        # 追加到非列表应该抛出异常
        with pytest.raises(ValueError):
            await ctx.append("test_key", "item")

    @pytest.mark.asyncio
    async def test_append_to_non_existent_key(self):
        """测试追加到不存在的键"""
        event_bus = EventBus()
        event_callback = AsyncMock()
        event_bus.subscribe("ctx_changed", event_callback)
        
        ctx = ObservableCtx(event_bus=event_bus)
        
        # 追加到不存在的键应该创建新列表
        await ctx.append("new_list", "item1")
        
        # 验证值已追加
        assert ctx.get("new_list") == ["item1"]
        
        # 验证事件已发布
        event_callback.assert_called_once()

    def test_get(self):
        """测试获取值"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, test_key="test_value")
        
        # 获取存在的键
        assert ctx.get("test_key") == "test_value"
        
        # 获取不存在的键
        assert ctx.get("non_existent_key") is None
        
        # 获取不存在的键并提供默认值
        assert ctx.get("non_existent_key", "default") == "default"

    def test_to_dict(self):
        """测试转换为字典"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, key1="value1", key2="value2")
        
        # 转换为字典
        data_dict = ctx.to_dict()
        
        # 验证字典内容
        assert data_dict["key1"] == "value1"
        assert data_dict["key2"] == "value2"

    def test_contains(self):
        """测试键是否存在"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, test_key="test_value")
        
        # 检查存在的键
        assert "test_key" in ctx
        
        # 检查不存在的键
        assert "non_existent_key" not in ctx

    def test_getitem(self):
        """测试通过[]访问"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus, test_key="test_value")
        
        # 通过[]访问
        assert ctx["test_key"] == "test_value"
        
        # 访问不存在的键应该返回None
        assert ctx["non_existent_key"] is None

    def test_setitem(self):
        """测试通过[]设置"""
        event_bus = EventBus()
        ctx = ObservableCtx(event_bus=event_bus)
        
        # 通过[]设置
        ctx["test_key"] = "test_value"
        
        # 验证值已设置
        assert ctx.get("test_key") == "test_value"
        # 注意：通过[]设置不会触发事件
