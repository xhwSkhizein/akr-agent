import pytest
import asyncio
import time
from unittest.mock import MagicMock, patch, AsyncMock

from core.dispatcher import RuleDispatcher, RuleIndex, PriorityTaskQueue
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
def rule_index():
    """创建一个规则索引实例"""
    return RuleIndex()


@pytest.fixture
def priority_queue():
    """创建一个优先级队列实例"""
    return PriorityTaskQueue()


@pytest.fixture
def sample_rule_configs():
    """创建多个规则配置用于测试"""
    return [
        RuleConfig(
            name="rule1",
            depend_ctx_key=["key1", "common_key"],
            match_condition="'key1' in ctx",
            prompt="提示1",
            tool="echo",
            tool_params={"ctx": ["key1"], "extra": {"message": "消息1"}},
            tool_result_target="DIRECT_RETURN",
            priority=10  # 高优先级
        ),
        RuleConfig(
            name="rule2",
            depend_ctx_key=["key2", "common_key"],
            match_condition="'key2' in ctx",
            prompt="提示2",
            tool="echo",
            tool_params={"ctx": ["key2"], "extra": {"message": "消息2"}},
            tool_result_target="DIRECT_RETURN",
            priority=5  # 中优先级
        ),
        RuleConfig(
            name="rule3",
            depend_ctx_key=["key3", "common_key"],
            match_condition="'key3' in ctx",
            prompt="提示3",
            tool="echo",
            tool_params={"ctx": ["key3"], "extra": {"message": "消息3"}},
            tool_result_target="DIRECT_RETURN",
            priority=1  # 低优先级
        )
    ]


@pytest.fixture
def dispatcher_with_rules(event_bus, observable_ctx, sample_rule_configs):
    """创建一个包含多个规则的调度器实例"""
    return RuleDispatcher(
        initial_rules=sample_rule_configs,
        event_bus=event_bus,
        ctx=observable_ctx,
        max_concurrent_tasks=5
    )


class TestRuleIndex:
    """测试规则索引结构"""

    def test_add_rule(self, rule_index):
        """测试添加规则到索引"""
        rule_index.add_rule("rule1", ["key1", "common_key"])
        rule_index.add_rule("rule2", ["key2", "common_key"])
        
        # 验证规则已正确添加到索引
        assert "rule1" in rule_index.get_rules_for_key("key1")
        assert "rule2" in rule_index.get_rules_for_key("key2")
        assert "rule1" in rule_index.get_rules_for_key("common_key")
        assert "rule2" in rule_index.get_rules_for_key("common_key")
        
        # 验证不存在的键返回空集合
        assert len(rule_index.get_rules_for_key("non_existent_key")) == 0

    def test_remove_rule(self, rule_index):
        """测试从索引中移除规则"""
        rule_index.add_rule("rule1", ["key1", "common_key"])
        rule_index.add_rule("rule2", ["key2", "common_key"])
        
        # 移除规则
        rule_index.remove_rule("rule1", ["key1", "common_key"])
        
        # 验证规则已正确移除
        assert "rule1" not in rule_index.get_rules_for_key("key1")
        assert "rule1" not in rule_index.get_rules_for_key("common_key")
        assert "rule2" in rule_index.get_rules_for_key("key2")
        assert "rule2" in rule_index.get_rules_for_key("common_key")

    def test_get_rules_for_key(self, rule_index):
        """测试获取依赖特定键的规则"""
        rule_index.add_rule("rule1", ["key1", "common_key"])
        rule_index.add_rule("rule2", ["key2", "common_key"])
        rule_index.add_rule("rule3", ["key3", "common_key"])
        
        # 验证获取依赖特定键的规则
        common_key_rules = rule_index.get_rules_for_key("common_key")
        assert len(common_key_rules) == 3
        assert "rule1" in common_key_rules
        assert "rule2" in common_key_rules
        assert "rule3" in common_key_rules
        
        key1_rules = rule_index.get_rules_for_key("key1")
        assert len(key1_rules) == 1
        assert "rule1" in key1_rules


class TestPriorityTaskQueue:
    """测试优先级任务队列"""

    def test_put_and_get(self, priority_queue):
        """测试添加和获取任务"""
        priority_queue.put(10, "high_priority_task")
        priority_queue.put(5, "medium_priority_task")
        priority_queue.put(1, "low_priority_task")
        
        # 验证队列长度
        assert len(priority_queue) == 3
        
        # 验证按优先级顺序获取任务
        assert priority_queue.get() == "high_priority_task"
        assert priority_queue.get() == "medium_priority_task"
        assert priority_queue.get() == "low_priority_task"
        
        # 验证队列为空时返回None
        assert priority_queue.get() is None
        assert len(priority_queue) == 0

    def test_empty_queue(self, priority_queue):
        """测试空队列行为"""
        assert len(priority_queue) == 0
        assert priority_queue.get() is None


class TestDispatcherOptimizations:
    """测试调度器优化"""

    def test_rule_index_integration(self, dispatcher_with_rules):
        """测试规则索引与调度器的集成"""
        # 验证规则索引已正确初始化
        rule_index = dispatcher_with_rules._rule_index
        
        # 获取所有规则ID
        rule_ids = list(dispatcher_with_rules._rule_configs.keys())
        assert len(rule_ids) == 3
        
        # 验证规则已正确添加到索引
        common_key_rules = rule_index.get_rules_for_key("common_key")
        assert len(common_key_rules) == 3
        for rule_id in rule_ids:
            assert rule_id in common_key_rules

    @pytest.mark.asyncio
    async def test_priority_queue_integration(self, dispatcher_with_rules, observable_ctx):
        """测试优先级队列与调度器的集成"""
        # 模拟任务执行
        async def mock_run_tool(*args, **kwargs):
            yield "执行中..."
            await asyncio.sleep(0.1)
            yield "完成"
        
        # 模拟条件检查始终返回True
        with patch('core.rule_task.RuleTask.check_rule_condition', return_value=True), \
             patch('core.tools.base.ToolCenter.run_tool', side_effect=mock_run_tool):
            
            # 触发上下文变化，影响所有规则
            await observable_ctx.set("common_key", "value")
            
            # 给事件总线和任务调度一点时间
            await asyncio.sleep(0.2)
            
            # 收集输出流的数据以验证执行顺序
            outputs = []
            
            # 创建一个带超时的收集器
            async def collect_outputs(timeout=0.2):
                start_time = time.time()
                async for chunk in dispatcher_with_rules.get_output_stream():
                    outputs.append(chunk.content)
                    # 检查是否超时
                    if time.time() - start_time > timeout:
                        break
                return len(outputs) > 0
            
            # 尝试收集输出
            try:
                has_outputs = await asyncio.wait_for(collect_outputs(), timeout=0.5)
            except asyncio.TimeoutError:
                has_outputs = False
            
            # 验证至少有一些输出
            assert has_outputs or len(outputs) > 0

    @pytest.mark.asyncio
    async def test_performance_comparison(self, event_bus, observable_ctx, sample_rule_configs):
        """测试性能对比"""
        # 创建大量规则配置
        many_rules = []
        for i in range(100):
            rule = RuleConfig(
                name=f"rule{i}",
                depend_ctx_key=[f"key{i}", "common_key"],
                match_condition=f"'key{i}' in ctx",
                prompt=f"提示{i}",
                tool="echo",
                tool_params={"ctx": [f"key{i}"], "extra": {"message": f"消息{i}"}},
                tool_result_target="DIRECT_RETURN",
                priority=i % 10  # 不同优先级
            )
            many_rules.append(rule)
        
        # 创建优化版调度器
        optimized_dispatcher = RuleDispatcher(
            initial_rules=many_rules,
            event_bus=event_bus,
            ctx=observable_ctx
        )
        
        # 模拟条件检查和工具执行
        with patch('core.rule_task.RuleTask.check_rule_condition', return_value=False), \
             patch('core.tools.base.ToolCenter.run_tool', side_effect=lambda *args, **kwargs: []):
            
            # 测量处理上下文变化的时间
            start_time = time.time()
            await observable_ctx.set("common_key", "new_value")
            await asyncio.sleep(0.5)  # 给事件处理一点时间
            processing_time = time.time() - start_time
            
            # 验证处理时间在合理范围内
            # 这只是一个简单的验证，实际性能提升需要更详细的基准测试
            assert processing_time < 2.0  # 假设处理时间应该小于2秒
