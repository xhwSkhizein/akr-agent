import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

from core.dispatcher import RuleDispatcher
from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from core.rule_config import RuleConfig
from core.rule_task import RuleTask
from core.task_state import TaskState


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
        ctx=observable_ctx,
        max_concurrent_tasks=5  # 设置较小的并发任务数用于测试
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
        rule_id = dispatcher.add_new_rule(new_rule)
        
        # 验证规则已添加
        assert rule_id in dispatcher._rule_configs
        assert dispatcher._rule_configs[rule_id] == new_rule
        
        # 验证优先级已设置
        assert rule_id in dispatcher._rule_priorities

    @pytest.mark.asyncio
    async def test_handle_ctx_changed(self, dispatcher, observable_ctx):
        """测试上下文变化处理"""
        # 直接在模拟函数中使用 yield
        async def mock_run_tool(*args, **kwargs):
            yield "Starting..."
            await asyncio.sleep(0.5)  # 暂停一会儿
            yield "Still running..."
        
        # 模拟 RuleTask.check_rule_condition 始终返回 True
        with patch('core.rule_task.RuleTask.check_rule_condition', return_value=True), \
             patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 模拟上下文变化
            await observable_ctx.set("test_key", "test_value")
            
            # 给事件总线一点时间处理事件
            await asyncio.sleep(0.5)
            
            # 验证任务已被创建和调度
            assert len(dispatcher._tasks) > 0
            assert len(dispatcher._active_task_executions) > 0
            
            # 验证任务状态
            for task_id, task in dispatcher._tasks.items():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    assert task.is_executing()
                    assert task.get_state() == TaskState.EXECUTING
            
            # 清理：等待任务完成
            await asyncio.sleep(0.8)

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
    async def test_shutdown(self, dispatcher: RuleDispatcher):
        """测试关闭调度器"""
        # 创建一个模拟任务
        mock_task = asyncio.create_task(asyncio.sleep(10))
        dispatcher._active_task_executions.add(mock_task)
    
        # 添加一个未完成的任务
        new_rule_config = RuleConfig(
            name="test_shutdown_rule",
            depend_ctx_key=["shutdown_key"],
            match_condition="'shutdown_key' in ctx",
            prompt="测试关闭",
            tool="echo",
            tool_params={
                "ctx": ["shutdown_key"],
                "extra": {"message": "测试关闭消息"}
            },
            tool_result_target="DIRECT_RETURN",
        )
        # 添加规则配置
        rule_id = dispatcher.add_new_rule(new_rule_config)
        
        # 手动创建一个任务实例用于测试
        task_id = dispatcher._generate_task_id(rule_id)
        task = RuleTask(rule_config=new_rule_config, task_id=task_id, rule_id=rule_id)
        dispatcher._tasks[task_id] = task
        
        # 关闭调度器
        await dispatcher.shutdown()
    
        # 验证所有任务都被取消
        assert len(dispatcher._active_task_executions) == 0
        assert mock_task.cancelled()
    
        # 验证所有未完成的任务都被标记为失败
        await asyncio.sleep(0.1)  # 等待异步状态转换
        assert dispatcher._tasks[task_id].is_completed()
        
        # 验证资源清理
        # 在关闭时规则配置保留，但优先级和任务活动时间被清空
        assert rule_id in dispatcher._rule_configs
        assert len(dispatcher._rule_priorities) == 0  # 优先级应该被清空
        assert len(dispatcher._task_last_activity) == 0

    @pytest.mark.asyncio
    async def test_task_execution_success(self, dispatcher, observable_ctx):
        """测试任务成功执行"""
        # 直接在模拟函数中使用 yield
        async def mock_run_tool(*args, **kwargs):
            yield "成功执行"
        
        # 只模拟 ToolCenter.run_tool，不模拟 wait_for
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务一点时间执行
            await asyncio.sleep(0.3)
            
            # 等待输出出现在队列中
            success_found = False
            # 尝试最多 5 次获取输出
            for _ in range(5):
                if not dispatcher._output_queue.empty():
                    output = await dispatcher._output_queue.get()
                    if "成功执行" in output:
                        success_found = True
                        break
                await asyncio.sleep(0.1)
            
            # 验证输出
            assert success_found
            
            # 验证任务状态
            await asyncio.sleep(0.1)  # 等待任务状态更新
            for task_id, task in dispatcher._tasks.items():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    assert task.is_completed()
                    assert task.get_state() == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_task_execution_error(self, dispatcher, observable_ctx):
        """测试任务执行出错"""
        # 模拟工具执行失败
        async def mock_run_tool(*args, **kwargs):
            # 首先输出一个错误消息，然后抛出异常
            yield "错误消息: 测试错误"
            raise Exception("测试错误")
        
        # 不再模拟 wait_for，使用真实的 wait_for 函数
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务一点时间执行
            await asyncio.sleep(0.3)
            
            # 验证任务状态
            for task in dispatcher._tasks.values():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    assert task.is_completed()
                    assert task.get_state() == TaskState.FAILED
            
            # 等待错误消息被添加到输出队列
            await asyncio.sleep(0.1)
            
            # 收集输出以检查错误消息
            error_found = False
            # 尝试最多 5 次获取输出
            for _ in range(5):
                if not dispatcher._output_queue.empty():
                    output = await dispatcher._output_queue.get()
                    if "错误" in output or "Error" in output:
                        error_found = True
                        break
                await asyncio.sleep(0.1)
            
            # 验证找到了错误消息
            assert error_found
