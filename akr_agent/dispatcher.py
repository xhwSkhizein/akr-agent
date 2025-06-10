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
    """
    Dynamic dispatcher for task management and rule execution
    """

    def __init__(
        self,
        initial_rules: List[RuleConfig],
        workspace_manager: WorkspaceManager,
        context_manager: ContextManager,
        max_concurrent_tasks: int,
        timeout_detection_time: int,
        stream_registration_timeout: int,
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
        self._output_manager = OutputStreamManager(logger=logger, stream_registration_timeout=stream_registration_timeout)
        self._task_manager = TaskManager(
            self._context_manager,
            executor=self._task_executor,
            output_manager=self._output_manager,
            logger=self._logger,
            max_concurrent_tasks=max_concurrent_tasks,
            timeout_detection_time=timeout_detection_time,
        )
        # Initialize rules
        if initial_rules:
            for rule_config in initial_rules:
                self.add_rule(rule_config)

        # Subscribe to context changes
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
        Handle context changes
        """
        changed_key = event.data["key"]
        new_value = event.data["value"]
        old_value = event.data["old_value"]
        self._logger.info(
            f"Context changed: key='{changed_key}', value='{new_value}', old_value='{old_value}'"
        )
        # Get all rules depending on this key
        dependent_rules = self._rule_registry.get_rules_for_key(changed_key)
        self._logger.info(
            f"Found {len(dependent_rules)} rules depending on key '{changed_key}'"
        )
        # Check each rule and create task
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
        """Add new rule"""
        rule_id = self._rule_registry.register_rule(rule_config)
        # If immediate check is needed, check conditions and create tasks if satisfied
        if immediate:
            asyncio.create_task(self._check_and_create_task(rule_id))

        return rule_id

    async def _check_and_create_task(self, rule_id: str) -> None:
        """Check rule conditions and create tasks if satisfied"""
        # Check if there are any active tasks for this rule
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

        # Check rule conditions
        if not self._rule_registry.check_rule_condition(
            rule_id, self._context_manager.get_context()
        ):
            self._logger.info(
                f"Rule {rule_id} does not meet the condition. Skipping task creation."
            )
            return

        # Condition satisfied, create new task
        rule_config = self._rule_registry.get_rule(rule_id)
        task_id = await self._task_manager.create_task_and_schedule(
            rule_id, rule_config
        )
        self._logger.info(
            f"Created new task {task_id} for rule {rule_id}, priority={rule_config.priority}"
        )

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """Provide final output as an async generator"""
        try:
            # Continuously check if there are any active tasks or pending tasks
            while True:
                # Check if there is any output available
                has_output = False
                async for chunk in self._output_manager.get_output_stream():
                    has_output = True
                    yield chunk

                # Check if all tasks are completed
                active_tasks = self._task_manager.get_active_tasks()
                active_task_count = len(active_tasks)
                # If there are no active tasks and no output, end the stream
                if not active_tasks and not has_output and active_task_count == 0:
                    self._logger.info("All tasks are completed and output stream is exhausted, ending output stream")
                    break
                self._logger.info(f"Waiting for output stream, current active task count: {active_task_count}")
                if active_task_count > 0:
                    await asyncio.sleep(0.2)
                else:
                    break
        finally:
            self._logger.info("Output stream ended")

    async def shutdown(self) -> None:
        """Shutdown dispatcher and clean up resources"""
        self._logger.info("Shutting down Dispatcher...")
        # Close task manager
        await self._task_manager.shutdown()
        self._logger.info("Dispatcher shutdown complete")
