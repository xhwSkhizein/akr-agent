import pytest
import asyncio
import uuid
from unittest.mock import MagicMock, patch, AsyncMock

from core.dispatcher import RuleDispatcher
from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from core.rule_config import RuleConfig
from core.rule_task import RuleTask


@pytest.fixture
def event_bus():
    """创建一个事件总线实例"""
    return EventBus()


@pytest.fixture
def observable_ctx(event_bus):
    """创建一个可观察上下文实例"""
    return ObservableCtx(event_bus=event_bus)


@pytest.fixture
def sample_rule_config():
    """创建一个简单的规则配置用于测试"""
    return RuleConfig(
        name="test_rule",
        depend_ctx_key=["test_key"],
        match_condition="'test_key' in ctx and ctx.get('test_key') == 'test_value'",
        prompt="测试提示",
        tool="echo",
        tool_params={
            "ctx": ["test_key"],
            "config": ["prompt"],
            "extra": {"message": "测试消息"}
        },
        tool_result_target="DIRECT_RETURN",
        tool_result_key=None
    )


@pytest.fixture
def dispatcher(event_bus, observable_ctx, sample_rule_config):
    """创建一个调度器实例"""
    return RuleDispatcher(
        initial_rules=[sample_rule_config],
        event_bus=event_bus,
        ctx=observable_ctx
    )


class TestRuleDispatcher:
    """测试RuleDispatcher类"""

    @pytest.mark.asyncio
    async def test_add_new_rule(self, dispatcher, sample_rule_config):
        """测试添加新规则"""
        # 添加一个新规则
        new_rule = RuleConfig(
            name="new_test_rule",
            depend_ctx_key=["new_key"],
            match_condition="'new_key' in ctx and ctx.get('new_key') == 'new_value'",
            prompt="新测试提示",
            tool="echo",
            tool_params={
                "ctx": ["new_key"],
                "config": ["prompt"],
                "extra": {"message": "新测试消息"}
            },
            tool_result_target="DIRECT_RETURN",
            tool_result_key=None
        )
        task_id = dispatcher.add_new_rule(new_rule)
        
        # 验证规则已添加
        assert task_id in dispatcher._tasks
        assert dispatcher._tasks[task_id].rule_config == new_rule

    @pytest.mark.asyncio
    async def test_handle_ctx_changed(self, dispatcher, observable_ctx):
        """测试上下文变化处理"""
        # 模拟工具执行，使用一个长时间运行的异步生成器
        async def mock_run_tool(*args, **kwargs):
            # 这个工具会长时间运行，让我们有时间检查任务是否在执行
            yield "Starting..."
            await asyncio.sleep(0.5)  # 暂停一会儿
            yield "Still running..."
        
        # 模拟 ToolCenter.run_tool
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 模拟上下文变化
            await observable_ctx.set("test_key", "test_value")
            
            # 给事件总线一点时间处理事件
            await asyncio.sleep(0.1)
            
            # 验证任务已被调度（至少有一个活动任务执行）
            assert len(dispatcher._active_task_executions) > 0
            
            # 清理：等待任务完成
            await asyncio.sleep(0.6)

    @pytest.mark.asyncio
    async def test_get_output_stream(self, dispatcher, observable_ctx):
        """测试输出流获取"""
        # 模拟一些输出
        await dispatcher._output_queue.put("测试输出1")
        await dispatcher._output_queue.put("测试输出2")
        
        # 收集输出
        outputs = []
        async for chunk in dispatcher.get_output_stream():
            outputs.append(chunk)
            if len(outputs) >= 2:  # 只收集前两个输出
                break
        
        # 验证输出
        assert "测试输出1" in outputs
        assert "测试输出2" in outputs

    @pytest.mark.asyncio
    async def test_shutdown(self, dispatcher):
        """测试关闭调度器"""
        # 创建一个模拟任务
        mock_task = asyncio.create_task(asyncio.sleep(10))
        dispatcher._active_task_executions.add(mock_task)
        
        # 关闭调度器
        await dispatcher.shutdown()
        
        # 验证所有任务都被取消
        assert len(dispatcher._active_task_executions) == 0
        assert mock_task.cancelled()

    @pytest.mark.asyncio
    async def test_task_execution_success(self, dispatcher, observable_ctx):
        """测试任务成功执行"""
        # 模拟工具执行
        async def mock_run_tool(*args, **kwargs):
            yield "成功执行"
        
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务一点时间执行
            await asyncio.sleep(0.2)
            
            # 收集输出
            outputs = []
            async for chunk in dispatcher.get_output_stream():
                outputs.append(chunk)
                if "成功执行" in chunk:
                    break
            
            # 验证输出
            assert "成功执行" in "".join(outputs)

    @pytest.mark.asyncio
    async def test_task_execution_error(self, dispatcher, observable_ctx):
        """测试任务执行出错"""
        # 模拟工具执行失败
        async def mock_run_tool(*args, **kwargs):
            raise Exception("测试错误")
        
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务一点时间执行
            await asyncio.sleep(0.2)
            
            # 验证任务状态
            for task in dispatcher._tasks.values():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    assert task.is_completed()
                    # 这里我们无法直接检查 _success 标志，因为它是私有的
                    # 但可以通过其他方式验证，比如检查输出队列中是否有错误消息
