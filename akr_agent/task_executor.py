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
    """工具调用达到最大重试次数"""

    error_msg: str

    def __init__(self, error_msg: str):
        self.error_msg = error_msg
        super().__init__(error_msg)


class TaskExecutor:
    """任务执行器，负责执行任务并处理结果"""

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
        """准备工具调用参数"""
        rule_config: RuleConfig = task_info.rule_config

        tool_params = {}

        # 从上下文获取参数
        ctx_keys = rule_config.tool_params.get("ctx", [])
        for key in ctx_keys:
            tool_params[key] = self._context_manager.get_context().get(key)

        # 从规则配置获取参数
        config_keys = rule_config.tool_params.get("config", [])
        for key in config_keys:
            tool_params[key] = getattr(rule_config, key)

        # 添加额外参数
        extra_params = rule_config.tool_params.get("extra", {})
        tool_params.update(extra_params)

        # 添加上下文和规则配置
        tool_params["ctx"] = self._context_manager.get_context()
        tool_params["ctx_manager"] = self._context_manager
        tool_params["rule_config"] = rule_config

        return tool_params

    async def _handle_tool_result(
        self, task_info: TaskInfo, response_full: str
    ) -> None:
        """处理工具调用结果"""
        rule_config: RuleConfig = task_info.rule_config

        if rule_config.tool_result_target == "DIRECT_RETURN":
            # 保存到对话历史
            await self._context_manager.emit_and_append_to_history(
                TextResult(text=response_full)
            )

        elif rule_config.tool_result_target == "AS_CONTEXT":
            # 保存到上下文
            self._context_manager.get_context().set(
                rule_config.tool_result_key, response_full
            )
            await self._context_manager.emit_and_append_to_history(
                AIContext(context=response_full)
            )

        elif rule_config.tool_result_target == "NEW_RULES":
            # 解析并生成新规则
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
        """执行任务的内部实现"""
        start_time = time.time()
        task_id = task_info.task_id
        rule_config: RuleConfig = task_info.rule_config
        response_full = ""
        error_msg = None

        async def emit_error(msg: str, error_type: str = "failed") -> None:
            """辅助函数：发送错误信息并更新状态"""
            nonlocal error_msg
            error_msg = msg
            yield msg

            execution_time = time.time() - start_time
            if error_type == "cancelled":
                self._context_manager.emit_task_cancelled(task_info, msg)
            else:
                self._context_manager.emit_task_failed(task_info, execution_time, msg)

        try:
            # 1. 准备工具调用参数
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

            # 2. 执行工具调用
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
                raise  # 重新抛出取消异常
            except Exception as e:
                self._logger.error(
                    f"Task {task_id}: Tool {rule_config.tool} execution failed: {e}"
                )
                async for chunk in emit_error(
                    f"Error: Tool {rule_config.tool} execution failed: {e}"
                ):
                    yield chunk
                return

            # 3. 处理工具调用结果
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

            # 任务成功完成
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
            raise  # 重新抛出取消异常

        except Exception as e:
            self._logger.error(
                f"Task {task_id}: Unexpected error in execute_task: {e}", exc_info=True
            )
            async for chunk in emit_error(
                f"Task {task_id}: Unexpected error in execute_task: {e}"
            ):
                yield chunk

    async def run_task(self, task_info: TaskInfo) -> AsyncGenerator[str, None]:
        """运行任务并支持取消

        这个方法创建一个异步任务并将其存储在 _executing_tasks 字典中，以便可以取消任务
        """
        task_id = task_info.task_id

        # 创建一个内部函数，用于包装 execute_task 并在完成后清理任务
        async def _task_wrapper():
            try:
                async for chunk in self._execute_task(task_info):
                    yield chunk
            finally:
                # 任务完成后从字典中移除
                if task_id in self._executing_tasks:
                    del self._executing_tasks[task_id]

        # 创建异步生成器
        gen = _task_wrapper().__aiter__()

        # 创建一个任务来运行生成器
        task = asyncio.create_task(gen.__anext__())
        self._executing_tasks[task_id] = task

        # 返回生成器的结果
        try:
            while True:
                try:
                    # 等待当前块
                    result = await task
                    yield result

                    # 创建下一个块的任务
                    task = asyncio.create_task(gen.__anext__())
                    self._executing_tasks[task_id] = task
                except StopAsyncIteration:
                    # 生成器已完成
                    break
        finally:
            # 确保任务从字典中移除
            if task_id in self._executing_tasks:
                del self._executing_tasks[task_id]

    async def cancel_task(self, task_id: str) -> None:
        """取消任务"""
        self._logger.info(f"Cancelling task {task_id}")
        if task_id in self._executing_tasks:
            task = self._executing_tasks[task_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # 任务会在 run_task 的 finally 块中从字典中移除
