import logging
import asyncio
from typing import List, AsyncGenerator
from .workspace_manager import WorkspaceManager
from .context_manager import ContextManager
from .event_bus import EventType, RealTimeEvent
from .llm.llm_base import TextPrompt
from .task_manager import TaskManager
from .rule_registery import RuleRegistry
from .task_executor import TaskExecutor
from .output_stream_manager import OutputStreamManager, OutputChunk
from .rule_config import RuleConfig


class DynamicDispatcher:

    def __init__(
        self,
        initial_rules: List[RuleConfig],
        workspace_manager: WorkspaceManager,
        context_manager: ContextManager,
        max_concurrent_tasks: int,
        timeout_detection_time: int,
        logger: logging.Logger,
    ):
        self._rules = initial_rules
        self._workspace_manager = workspace_manager
        self._context_manager = context_manager
        self._logger = logger
        self._rule_registry = RuleRegistry()
        self._task_executor = TaskExecutor(
            self._rule_registry, self._context_manager, self._logger
        )
        self._output_manager = OutputStreamManager(logger=logger)
        self._task_manager = TaskManager(
            self._context_manager,
            executor=self._task_executor,
            output_manager=self._output_manager,
            logger=self._logger,
            max_concurrent_tasks=max_concurrent_tasks,
            timeout_detection_time=timeout_detection_time,
        )
        # 初始化规则
        if initial_rules:
            for rule_config in initial_rules:
                self.add_rule(rule_config)

        # 订阅上下文变化事件
        self._context_manager.subscribe(
            EventType.CONTEXT_CHANGED, self._handle_ctx_changed
        )
        self._context_manager.subscribe(
            EventType.NEW_RULE_GENERATED, self._handle_new_rule_generated
        )
        self._context_manager.subscribe(
            EventType.NEW_RULE_GENERATED, self._handle_new_rule_generated
        )
        # TODO: more events

    async def _handle_ctx_changed(self, event: RealTimeEvent) -> None:
        """
        处理上下文变化事件
        """
        changed_key = event.data["key"]
        new_value = event.data["value"]
        old_value = event.data["old_value"]
        self._logger.info(
            f"Context changed: key='{changed_key}', value='{new_value}', old_value='{old_value}'"
        )
        # 获取依赖此键的所有规则
        dependent_rules = self._rule_registry.get_rules_for_key(changed_key)
        self._logger.info(
            f"Found {len(dependent_rules)} rules depending on key '{changed_key}'"
        )
        # 检查每个规则并创建任务
        for rule_id in dependent_rules:
            await self._check_and_create_task(rule_id)

    async def _handle_new_rule_generated(self, event: RealTimeEvent):
        event_data = event.data
        task_id = event_data["task_id"]
        rule_config = event_data["rule_config"]
        immediate = event_data.get("immediate", False)
        self._logger.info(
            f"New rule generated: {rule_config} by task {task_id}, immediate={immediate}"
        )
        await self.add_rule(rule_config=rule_config, immediate=immediate)

    async def add_user_input(self, user_input: str):
        self._logger.info(f"Received user input: {user_input}")
        text_prompt = TextPrompt(text=user_input)
        await self._context_manager.emit_and_append_to_history(text_prompt)

    def add_rule(self, rule_config: RuleConfig, immediate: bool = False) -> str:
        """添加新规则"""
        rule_id = self._rule_registry.register_rule(rule_config)
        # 如果需要立即检查，则检查条件并在满足时创建任务
        if immediate:
            asyncio.create_task(self._check_and_create_task(rule_id))

        return rule_id

    async def _check_and_create_task(self, rule_id: str) -> None:
        """检查规则条件，如果满足则创建任务"""
        # 检查是否有该规则的任务正在执行
        rule_tasks = self._task_manager.get_tasks_by_rule(rule_id)
        active_tasks = [
            task_id
            for task_id in rule_tasks
            if self._task_manager.is_task_executing(task_id)
        ]

        if active_tasks:
            self._logger.info(
                f"Rule {rule_id} already has active tasks. Skipping task creation."
            )
            return

        # 检查规则条件
        if not self._rule_registry.check_rule_condition(
            rule_id, self._context_manager.get_context()
        ):
            self._logger.info(
                f"Rule {rule_id} does not meet the condition. Skipping task creation."
            )
            return

        # 条件满足，创建新任务
        rule_config = self._rule_registry.get_rule(rule_id)
        task_id = await self._task_manager.create_task_and_schedule(
            rule_id, rule_config
        )
        self._logger.info(
            f"Created new task {task_id} for rule {rule_id}, priority={rule_config.priority}"
        )

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """提供最终输出的异步生成器"""
        try:
            # 持续检查是否有任务正在执行或等待调度
            while True:
                # 检查是否有输出可用
                has_output = False
                async for chunk in self._output_manager.get_output_stream():
                    has_output = True
                    yield chunk

                # 检查是否所有任务都已完成
                active_tasks = self._task_manager.get_active_tasks()
                active_task_count = len(active_tasks)
                # 如果没有活动任务且没有输出，则结束
                if not active_tasks and not has_output and active_task_count == 0:
                    self._logger.info("所有任务已完成且输出流已耗尽，结束输出流")
                    break
                self._logger.info(f"等待输出流，当前活动任务数: {active_task_count}")
                if active_task_count > 0:
                    await asyncio.sleep(0.2)
                else:
                    break
        finally:
            self._logger.info("结束输出流")

    async def shutdown(self) -> None:
        """关闭调度器并清理资源"""
        self._logger.info("Shutting down Dispatcher...")
        # 关闭任务管理器
        await self._task_manager.shutdown()
        self._logger.info("Dispatcher shutdown complete")
