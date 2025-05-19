import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock
import contextlib

from core.dispatcher import RuleDispatcher, RuleIndex, PriorityTaskQueue
from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from core.rule_config import RuleConfig
from core.rule_task import RuleTask
from core.task_state import TaskState
from core.output_stream import OutputStreamManager, StreamMetadata, OutputChunk


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
async def dispatcher(event_bus, observable_ctx, sample_rule_config):
    """创建一个调度器实例，并在测试结束后自动关闭"""
    disp = RuleDispatcher(
        initial_rules=[sample_rule_config],
        event_bus=event_bus,
        ctx=observable_ctx,
        max_concurrent_tasks=5,
        deadlock_detection_time=10
    )
    
    yield disp
    
    # 测试结束后关闭调度器
    await disp.shutdown()


class TestOutputStreamIntegration:
    """测试输出流优化与调度器的集成"""
    
    @pytest.mark.asyncio
    async def test_output_stream_success(self, dispatcher, observable_ctx):
        """测试成功执行任务时的输出流"""
        # 模拟工具执行成功
        async def mock_run_tool(*args, **kwargs):
            yield "执行中..."
            await asyncio.sleep(0.1)  # 短暂等待
            yield "执行成功"
        
        # 模拟工具执行
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务足够时间开始执行
            await asyncio.sleep(0.5)
            
            # 收集输出，使用超时控制
            outputs = []
            
            async def collect_outputs():
                async for chunk in dispatcher.get_output_stream():
                    outputs.append(chunk.content)
                    if "执行成功" in chunk.content:
                        # 找到成功消息后退出
                        return True
                return False
            
            # 使用超时机制收集输出
            try:
                await asyncio.wait_for(collect_outputs(), timeout=1.0)
            except asyncio.TimeoutError:
                pass  # 超时后继续执行
            
            # 验证输出内容
            assert any("执行中..." in output for output in outputs), f"输出中没有'执行中...'，实际输出: {outputs}"
            assert any("执行成功" in output for output in outputs), f"输出中没有'执行成功'，实际输出: {outputs}"
            
            # 等待任务完成
            await asyncio.sleep(0.5)
            
            # 验证任务状态
            task_completed = False
            for task in dispatcher._tasks.values():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    task_completed = task.is_completed()
                    break
            
            assert task_completed, "任务未完成"
            
        # 测试结束后显式关闭调度器
        # 注意：这里不需要再次关闭，因为我们使用了异步fixture，它会在测试结束后自动关闭调度器
    
    @pytest.mark.asyncio
    async def test_output_stream_error(self, dispatcher, observable_ctx):
        """测试执行任务出错时的输出流"""
        # 模拟工具执行失败
        async def mock_run_tool(*args, **kwargs):
            yield "开始执行..."
            await asyncio.sleep(0.1)  # 短暂等待
            raise Exception("模拟错误")
        
        # 模拟工具执行
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发任务执行
            await observable_ctx.set("test_key", "test_value")
            
            # 给任务足够时间开始执行
            await asyncio.sleep(0.5)
            
            # 收集输出
            outputs = []
            
            # 定义收集函数，使用更简单的方式
            async def collect_outputs():
                async for chunk in dispatcher.get_output_stream():
                    content = chunk.content
                    outputs.append(content)
                    # 如果找到错误消息，就退出
                    if "Error" in content or "错误" in content or "模拟错误" in content:
                        return True
                return False
            
            # 使用超时机制收集输出
            error_found = False
            try:
                error_found = await asyncio.wait_for(collect_outputs(), timeout=1.0)
            except asyncio.TimeoutError:
                pass  # 超时后继续执行
            
            # 验证输出内容
            start_message_found = any("开始执行..." in output for output in outputs)
            error_message_found = any("Error" in output or "错误" in output or "模拟错误" in output for output in outputs)
            
            assert start_message_found, f"输出中没有'开始执行...'，实际输出: {outputs}"
            assert error_found or error_message_found, f"输出中没有错误消息，实际输出: {outputs}"
            
            # 等待任务完成
            await asyncio.sleep(0.5)
            
            # 验证任务状态
            task_completed = False
            for task in dispatcher._tasks.values():
                if task.rule_config.depend_ctx_key == ["test_key"]:
                    # 任务应该完成，但状态应该是FAILED
                    task_completed = task.is_completed()
                    task_failed = task.get_state() == TaskState.FAILED
                    break
            
            assert task_completed, "任务未完成"
            assert task_failed, "任务未标记为失败"
            
        # 测试结束后显式关闭调度器
        # 注意：这里不需要再次关闭，因为我们使用了异步fixture，它会在测试结束后自动关闭调度器
    
    @pytest.mark.asyncio
    async def test_multiple_tasks_output(self, event_bus, observable_ctx):
        """测试多个任务并发执行时的输出流"""
        # 创建多个规则配置
        rule_configs = [
            RuleConfig(
                name=f"rule{i}",
                depend_ctx_key=["common_key"],
                match_condition="'common_key' in ctx",
                prompt=f"提示{i}",
                tool="echo",
                tool_params={"extra": {"message": f"消息{i}"}},
                tool_result_target="DIRECT_RETURN",
                priority=i  # 不同优先级
            )
            for i in range(1, 4)  # 创建3个规则
        ]
        
        # 创建调度器
        dispatcher = RuleDispatcher(
            initial_rules=rule_configs,
            event_bus=event_bus,
            ctx=observable_ctx
        )
        
        # 模拟工具执行，每个任务产生不同的输出
        async def mock_run_tool(*args, **kwargs):
            # 从参数中获取消息
            message = kwargs.get("message", "默认消息")
            yield f"开始: {message}"
            await asyncio.sleep(0.05)  # 短暂等待
            yield f"完成: {message}"
        
        # 模拟工具执行
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 触发所有任务执行
            await observable_ctx.set("common_key", "value")
            
            # 给任务足够时间开始执行
            await asyncio.sleep(0.5)
            
            # 收集输出，使用超时控制
            outputs = []
            message_count = {}
            
            # 定义收集函数
            async def collect_outputs():
                async for chunk in dispatcher.get_output_stream():
                    content = chunk.content
                    outputs.append(content)
                    
                    # 计算每个任务的消息数量
                    for i in range(1, 4):
                        if f"消息{i}" in content:
                            message_count[i] = message_count.get(i, 0) + 1
                    
                    # 如果每个任务都有至少2个消息，则退出
                    if all(message_count.get(i, 0) >= 2 for i in range(1, 4)):
                        return True
                    
                    # 或者如果收集了足够多的消息
                    if len(outputs) >= 10:  # 设置一个合理的上限
                        return True
                        
                return False
            
            # 使用超时机制收集输出
            try:
                await asyncio.wait_for(collect_outputs(), timeout=2.0)
            except asyncio.TimeoutError:
                pass  # 超时后继续执行
            
            # 验证每个任务的输出
            for i in range(1, 4):
                start_found = any(f"开始: 消息{i}" in output for output in outputs)
                complete_found = any(f"完成: 消息{i}" in output for output in outputs)
                
                assert start_found, f"没有找到任务{i}的开始消息，实际输出: {outputs}"
                assert complete_found, f"没有找到任务{i}的完成消息，实际输出: {outputs}"
            
            # 等待任务完成
            await asyncio.sleep(0.5)
            
            # 验证所有任务都已完成
            completed_tasks = 0
            for task in dispatcher._tasks.values():
                if task.is_completed():
                    completed_tasks += 1
            
            # 应该至少有3个完成的任务
            assert completed_tasks >= 3, f"只有{completed_tasks}个任务完成，应该有3个"
            
        # 测试结束后显式关闭调度器
        await dispatcher.shutdown()
