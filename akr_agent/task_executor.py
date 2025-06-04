from typing import Dict, Any, AsyncGenerator
import asyncio
import time
import logging
import json

from .rule_registery import RuleRegistry
from .context_manager import ContextManager
from .llm.llm_base import TextResult, AIContext
from .tools.base import ToolCenter
from .rule_config import RuleConfig
from .task_state import TaskInfo


class MaxRetryError(Exception):
    """Tool call reached maximum retry count"""

    error_msg: str

    def __init__(self, error_msg: str):
        self.error_msg = error_msg
        super().__init__(error_msg)


class TaskExecutor:
    """Task executor, responsible for executing tasks and handling results"""

    def __init__(
        self,
        rule_registry: RuleRegistry,
        context_manager: ContextManager,
        logger: logging.Logger,
        # event_bus: EventBus, # 响应复杂情况时使用
    ):
        self._rule_registry: RuleRegistry = rule_registry
        self._context_manager: ContextManager = context_manager
        self._logger: logging.Logger = logger
        self._executing_tasks: Dict[str, asyncio.Task] = {}

    async def _prepare_tool_params(self, task_info: TaskInfo) -> Dict[str, Any]:
        """Prepare tool call parameters"""
        rule_config: RuleConfig = task_info.rule_config

        tool_params = {}

        # Get parameters from context
        ctx_keys = rule_config.tool_params.get("ctx", [])
        for key in ctx_keys:
            tool_params[key] = self._context_manager.get_context().get(key)

        # Get parameters from rule config
        config_keys = rule_config.tool_params.get("config", [])
        for key in config_keys:
            tool_params[key] = getattr(rule_config, key)

        # Add extra parameters
        extra_params = rule_config.tool_params.get("extra", {})
        tool_params.update(extra_params)

        # Add context and rule config
        tool_params["ctx"] = self._context_manager.get_context()
        tool_params["ctx_manager"] = self._context_manager
        tool_params["rule_config"] = rule_config

        return tool_params

    async def _handle_tool_result(
        self, task_info: TaskInfo, response_full: str
    ) -> None:
        """Handle tool call result"""
        rule_config: RuleConfig = task_info.rule_config

        if rule_config.tool_result_target == "DIRECT_RETURN":
            # Save to conversation history
            await self._context_manager.emit_and_append_to_history(
                TextResult(text=response_full)
            )

        elif rule_config.tool_result_target == "AS_CONTEXT":
            # Save to context
            self._context_manager.get_context().set(
                rule_config.tool_result_key, response_full
            )
            await self._context_manager.emit_and_append_to_history(
                AIContext(context=response_full)
            )

        elif rule_config.tool_result_target == "NEW_RULES":
            # Parse and generate new rules
            new_rule_configs = RuleConfig.parse_and_gen(
                source=rule_config.name,
                tool_result_full=response_full,
                save=True,
            )
            await self._context_manager.emit_and_append_to_history(
                AIContext(context=response_full)
            )
            for new_cfg in new_rule_configs:
                new_cfg.auto_generated = True
                self._context_manager.emit_task_generate_new_rule(
                    task_info, new_cfg, immediate=True
                )

    async def _execute_task(self, task_info: TaskInfo) -> AsyncGenerator[str, None]:
        """Internal implementation of task execution"""
        start_time = time.time()
        task_id = task_info.task_id
        rule_config: RuleConfig = task_info.rule_config
        response_full = ""
        error_msg = None

        async def emit_error(msg: str, error_type: str = "failed") -> None:
            """Helper function: send error message and update status"""
            nonlocal error_msg
            error_msg = msg
            yield msg

            execution_time = time.time() - start_time
            if error_type == "cancelled":
                self._context_manager.emit_task_cancelled(task_info, msg)
            else:
                self._context_manager.emit_task_failed(task_info, execution_time, msg)

        try:
            # 1. Prepare tool call parameters
            try:
                tool_params = await self._prepare_tool_params(task_info)
                self._logger.info(
                    f"Task for Rule: {rule_config.name} {task_info.rule_id}: Tool params prepared"
                )
            except Exception as e:
                self._logger.error(
                    f"Error: Failed to prepare parameters for tool {rule_config.tool}: {e}"
                )
                async for chunk in emit_error(
                    f"Error: Failed to prepare parameters for tool {rule_config.tool}: {e}"
                ):
                    yield chunk
                return

            # 2. Execute tool call
            self._context_manager.emit_task_executing(task_info)
            try:
                async for chunk in ToolCenter.run_tool(
                    name=rule_config.tool, **tool_params
                ):
                    if rule_config.tool_result_target == "DIRECT_RETURN":
                        yield chunk
                    response_full += chunk
            except asyncio.CancelledError:
                self._logger.warning(f"Task {task_id}: Tool execution was cancelled")
                async for chunk in emit_error(
                    "Tool execution was cancelled", "cancelled"
                ):
                    yield chunk
                raise  # Re-raise cancellation error
            except Exception as e:
                self._logger.error(
                    f"Task {task_id}: Tool {rule_config.tool} execution failed: {e}"
                )
                async for chunk in emit_error(
                    f"Error: Tool {rule_config.tool} execution failed: {e}"
                ):
                    yield chunk
                return

            # 3. Handle tool call result
            if not response_full:
                self._logger.error(
                    f"Error: Tool {rule_config.tool}, task {task_id} returned empty result"
                )
                async for chunk in emit_error(
                    f"Error: Tool {rule_config.tool}, task {task_id} returned empty result"
                ):
                    yield chunk
                return

            try:
                await self._handle_tool_result(task_info, response_full)
                self._logger.info(f"Task {task_id}: Tool result handled")
            except json.JSONDecodeError as e:
                self._logger.error(
                    f"Error: Tool {rule_config.tool}, task {task_id} result handling failed (invalid format): {e}"
                )
                async for chunk in emit_error(
                    f"Error: Tool {rule_config.tool}, task {task_id} result handling failed (invalid format): {e}"
                ):
                    yield chunk
                return
            except Exception as e:
                self._logger.error(
                    f"Error: Tool {rule_config.tool}, task {task_id} result handling failed: {e}"
                )
                async for chunk in emit_error(
                    f"Error: Tool {rule_config.tool}, task {task_id} result handling failed: {e}"
                ):
                    yield chunk
                return

            # Task completed successfully
            execution_time = time.time() - start_time
            self._logger.info(
                f"Task {task_id} completed successfully in {execution_time:.2f}s"
            )
            self._context_manager.emit_task_completed(
                task_info, execution_time, response_full
            )

        except asyncio.CancelledError:
            self._logger.warning(f"Task {task_id} was cancelled")
            async for chunk in emit_error(f"Task {task_id} was cancelled", "cancelled"):
                yield chunk
            raise  # Re-raise cancellation error

        except Exception as e:
            self._logger.error(
                f"Task {task_id}: Unexpected error in execute_task: {e}", exc_info=True
            )
            async for chunk in emit_error(
                f"Task {task_id}: Unexpected error in execute_task: {e}"
            ):
                yield chunk

    async def run_task(self, task_info: TaskInfo) -> AsyncGenerator[str, None]:
        """Run task and support cancellation

        This method creates an async task and stores it in the _executing_tasks dictionary
        to allow cancellation of the task.
        """
        task_id = task_info.task_id

        # Create an internal function to wrap execute_task and clean up the task on completion
        async def _task_wrapper():
            try:
                async for chunk in self._execute_task(task_info):
                    yield chunk
            finally:
                # Remove task from dictionary on completion
                if task_id in self._executing_tasks:
                    del self._executing_tasks[task_id]

        # Create async generator
        gen = _task_wrapper().__aiter__()

        # Create a task to run the generator
        task = asyncio.create_task(gen.__anext__())
        self._executing_tasks[task_id] = task

        # Return generator results
        try:
            while True:
                try:
                    # Wait for current chunk
                    result = await task
                    yield result

                    # Create next chunk task
                    task = asyncio.create_task(gen.__anext__())
                    self._executing_tasks[task_id] = task
                except StopAsyncIteration:
                    # Generator completed
                    break
        finally:
            # Ensure task is removed from dictionary
            if task_id in self._executing_tasks:
                del self._executing_tasks[task_id]

    async def cancel_task(self, task_id: str) -> None:
        """Cancel task"""
        self._logger.info(f"Cancelling task {task_id}")
        if task_id in self._executing_tasks:
            task = self._executing_tasks[task_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # The task will be removed from the dictionary in the finally block of run_task
