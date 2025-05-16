import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

from core.rule_task import RuleTask
from core.rule_config import RuleConfig
from core.observable_ctx import ObservableCtx
from core.event_bus import EventBus


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
def rule_task(sample_rule_config):
    """创建一个规则任务实例"""
    return RuleTask(rule_config=sample_rule_config, task_id="test_task_id")


class TestRuleTask:
    """测试RuleTask类"""

    def test_initialization(self, rule_task, sample_rule_config):
        """测试任务初始化"""
        assert rule_task.rule_config == sample_rule_config
        assert rule_task.task_id == "test_task_id"
        assert not rule_task.is_completed()
        assert not rule_task.is_executing()

    def test_state_management(self, rule_task):
        """测试状态管理"""
        # 初始状态
        assert not rule_task.is_completed()
        assert not rule_task.is_executing()
        
        # 设置执行中
        rule_task.set_executing(True)
        assert rule_task.is_executing()
        
        # 设置已完成
        rule_task.set_completed(True, success=True)
        assert rule_task.is_completed()
        
        # 重置执行中状态
        rule_task.set_executing(False)
        assert not rule_task.is_executing()

    def test_condition_evaluation(self, rule_task, observable_ctx):
        """测试条件评估"""
        # 条件不满足
        assert not rule_task.is_condition_meet(observable_ctx)
        
        # 设置上下文使条件满足
        observable_ctx["test_key"] = "test_value"
        assert rule_task.is_condition_meet(observable_ctx)
        
        # 设置任务为已完成，条件应该不再满足
        rule_task.set_completed(True)
        assert not rule_task.is_condition_meet(observable_ctx)
        
        # 重置任务状态
        rule_task.set_completed(False)
        rule_task.set_executing(True)
        # 设置为执行中，条件应该不再满足
        assert not rule_task.is_condition_meet(observable_ctx)

    @pytest.mark.asyncio
    async def test_prepare_tool_params(self, rule_task, observable_ctx):
        """测试准备工具参数"""
        # 设置上下文
        observable_ctx["test_key"] = "test_value"
        
        # 准备参数
        params = await rule_task._prepare_tool_params(observable_ctx)
        
        # 验证参数
        assert params["test_key"] == "test_value"
        assert params["prompt"] == "测试提示"
        assert params["message"] == "测试消息"
        assert params["ctx"] == observable_ctx
        assert params["rule_config"] == rule_task.rule_config

    @pytest.mark.asyncio
    async def test_handle_tool_result_direct_return(self, rule_task, observable_ctx):
        """测试处理工具结果 - 直接返回"""
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 处理结果
        await rule_task._handle_tool_result(
            ctx=observable_ctx,
            dispatcher=mock_dispatcher,
            response_full="测试结果"
        )
        
        # 验证结果被添加到对话历史
        assert "测试结果" in observable_ctx.get("dialogue.history", [""])[0]

    @pytest.mark.asyncio
    async def test_handle_tool_result_as_context(self, rule_task, observable_ctx):
        """测试处理工具结果 - 作为上下文"""
        # 修改规则配置
        rule_task.rule_config.tool_result_target = "AS_CONTEXT"
        rule_task.rule_config.tool_result_key = "result_key"
        
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 处理结果
        await rule_task._handle_tool_result(
            ctx=observable_ctx,
            dispatcher=mock_dispatcher,
            response_full="测试结果"
        )
        
        # 验证结果被设置到上下文
        assert observable_ctx.get("result_key") == "测试结果"

    @pytest.mark.asyncio
    async def test_handle_tool_result_new_rules(self, rule_task, observable_ctx):
        """测试处理工具结果 - 新规则"""
        # 修改规则配置
        rule_task.rule_config.tool_result_target = "NEW_RULES"
        
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 模拟RuleConfig.parse_and_gen方法
        mock_rule_config = MagicMock()
        mock_parse_and_gen = MagicMock(return_value=[mock_rule_config])
        
        with patch('core.rule_config.RuleConfig.parse_and_gen', mock_parse_and_gen):
            # 处理结果
            await rule_task._handle_tool_result(
                ctx=observable_ctx,
                dispatcher=mock_dispatcher,
                response_full='{"name": "new_rule", "depend_ctx_key": ["key"], "prompt": "prompt", "tool_result_target": "DIRECT_RETURN"}'
            )
            
            # 验证新规则被添加
            mock_dispatcher.add_new_rule.assert_called_once()
            assert mock_dispatcher.add_new_rule.call_args[0][0] == mock_rule_config
            assert mock_dispatcher.add_new_rule.call_args[1]["immediate"] == True

    @pytest.mark.asyncio
    async def test_execute_tool_success(self, rule_task, observable_ctx):
        """测试执行工具 - 成功"""
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 模拟工具执行
        async def mock_run_tool(*args, **kwargs):
            yield "成功执行"
        
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 执行工具
            chunks = []
            async for chunk in rule_task.execute_tool(ctx=observable_ctx, dispatcher=mock_dispatcher):
                chunks.append(chunk)
            
            # 验证输出
            assert "成功执行" in chunks
            
            # 验证任务状态
            assert rule_task.is_completed()
            assert not rule_task.is_executing()

    @pytest.mark.asyncio
    async def test_execute_tool_error(self, rule_task, observable_ctx):
        """测试执行工具 - 错误"""
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 模拟工具执行失败
        async def mock_run_tool(*args, **kwargs):
            # 正确的模拟异步生成器失败
            if False:  # 这个条件保证生成器不会产生任何值
                yield ""  # 这行使得函数成为异步生成器
            raise Exception("测试错误")
        
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 执行工具
            chunks = []
            async for chunk in rule_task.execute_tool(ctx=observable_ctx, dispatcher=mock_dispatcher):
                chunks.append(chunk)
            
            # 验证输出包含错误信息
            assert any("错误" in chunk for chunk in chunks)
            
            # 验证任务状态
            assert rule_task.is_completed()
            assert not rule_task.is_executing()

    @pytest.mark.asyncio
    async def test_execute_tool_retry(self, rule_task, observable_ctx):
        """测试执行工具 - 重试"""
        # 创建模拟调度器
        mock_dispatcher = MagicMock()
        
        # 模拟工具执行 - 第一次失败，第二次成功
        retry_count = 0
        
        async def mock_run_tool(*args, **kwargs):
            nonlocal retry_count
            if retry_count == 0:
                retry_count += 1
                raise ConnectionError("连接错误")
            yield "重试成功"
        
        with patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            # 执行工具
            chunks = []
            async for chunk in rule_task.execute_tool(ctx=observable_ctx, dispatcher=mock_dispatcher):
                chunks.append(chunk)
            
            # 验证输出
            assert "重试成功" in chunks
            
            # 验证任务状态
            assert rule_task.is_completed()
            assert not rule_task.is_executing()
            
            # 验证重试次数
            assert retry_count == 1
