import logging
from typing import TYPE_CHECKING, AsyncGenerator, List, Optional
import json
import time
import asyncio
from core.tools.base import ToolCenter

from core.rule_config import RuleConfig
from core.observable_ctx import ObservableCtx
from core.task_state import TaskState, TaskStateTransitionError
from core.event_bus import EventType, ChangeType

if TYPE_CHECKING:
    from .dispatcher import RuleDispatcher  # Circular import for type hinting
    from .event_bus import EventBus

logger = logging.getLogger(__name__)


class RuleTask:
    def __init__(
        self,
        rule_config: RuleConfig,
        task_id: str,
        event_bus: "EventBus",
        rule_id: str = None,
    ):
        self.rule_config = rule_config
        self.task_id = task_id
        self.rule_id = rule_id  # 关联的规则ID
        self._state = TaskState.PENDING
        self._state_lock = asyncio.Lock()  # 用于保护状态转换的锁
        self._success = False  # 执行是否成功
        self._event_bus = event_bus  # 事件总线引用

    async def initialize(self) -> None:
        """异步初始化方法，用于发布任务创建事件"""
        await self._publish_task_event(ChangeType.TASK_CREATED)

    def is_completed(self) -> bool:
        """检查任务是否已完成（包括成功完成和失败）"""
        return self._state in (TaskState.COMPLETED, TaskState.FAILED)

    def is_executing(self) -> bool:
        """检查任务是否正在执行中"""
        return self._state == TaskState.EXECUTING

    def is_ready(self) -> bool:
        """检查任务是否准备好执行"""
        return self._state == TaskState.READY

    def get_state(self) -> TaskState:
        """获取当前任务状态"""
        return self._state

    def _is_valid_state_transition(self, new_state: TaskState) -> bool:
        """检查状态转换是否有效

        Args:
            new_state: 新状态

        Returns:
            是否是有效的状态转换
        """
        valid_transitions = {
            TaskState.PENDING: [TaskState.READY, TaskState.FAILED],
            TaskState.READY: [TaskState.EXECUTING, TaskState.FAILED],
            TaskState.EXECUTING: [TaskState.COMPLETED, TaskState.FAILED],
            TaskState.COMPLETED: [],  # 终态，不能再转换
            TaskState.FAILED: [],  # 终态，不能再转换
        }
        return new_state in valid_transitions[self._state]

    async def _publish_task_event(
        self,
        change_type: str,
        error: Optional[str] = None,
        old_state: Optional[TaskState] = None,
    ) -> None:
        """发布任务事件

        Args:
            change_type: 变化类型，来自 ChangeType 常量
            error: 如果是错误状态，提供错误信息
            old_state: 旧状态
        """
        event_data = {
            "task_id": self.task_id,
            "rule_id": self.rule_id,
            "rule_name": (
                self.rule_config.name if hasattr(self.rule_config, "name") else "N/A"
            ),
            "state": self._state,
            "old_state": old_state,
            "new_state": self._state,
            "change_type": change_type,
            "success": self._success,
            "error": error,
        }
        await self._event_bus.publish(EventType.TASK_CHANGED, **event_data)

    async def set_state(
        self,
        new_state: TaskState,
        success: Optional[bool] = None,
        error: Optional[str] = None,
    ) -> None:
        """设置任务状态

        Args:
            new_state: 新状态
            success: 是否成功完成
            error: 错误信息（如果有）

        Raises:
            TaskStateTransitionError: 无效的状态转换
        """
        async with self._state_lock:
            # 检查状态转换是否有效
            if not self._is_valid_state_transition(new_state):
                raise TaskStateTransitionError(
                    current_state=self._state, target_state=new_state
                )

            # 记录状态变化
            old_state = self._state
            self._state = new_state

            # 更新成功状态
            if success is not None:
                self._success = success

            # 记录状态变化
            logger.debug(
                f"Task {self.task_id} (Name: {self.rule_config.name}) state changed: {old_state.value} -> {new_state.value}"
            )

            # 发布状态变更事件
            await self._publish_task_event(
                ChangeType.TASK_STATE_CHANGED, error, old_state
            )
            logger.debug(
                f"Task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}) state changed: {old_state.value} -> {new_state.value}"
            )

    @staticmethod
    def check_condition(
        condition: str, ctx: ObservableCtx, log_id: str = "unknown"
    ) -> bool:
        """静态方法：检查条件是否满足，不需要创建任务实例

        Args:
            condition: 条件表达式
            ctx: 上下文对象
            log_id: 用于日志记录的ID

        Returns:
            条件是否满足
        """
        if condition:
            try:
                # Prepare context for eval - only allow access to ctx.get and builtins
                # A safer eval might use ast.literal_eval or a restricted eval environment
                eval_globals = {
                    "__builtins__": {
                        "True": True,
                        "False": False,
                        "None": None,
                        "str": str,
                        "int": int,
                        "float": float,
                        "bool": bool,
                        "list": list,
                        "dict": dict,
                        "set": set,
                        "tuple": tuple,
                        "len": len,
                        "Exception": Exception,
                    },
                    "ctx": ctx,
                }
                result = eval(condition, eval_globals, {})
                logger.debug(
                    f"Condition '{condition}' for {log_id} evaluated to: {result}"
                )
                return bool(result)
            except Exception as e:
                logger.error(f"Error evaluating condition for {log_id}: {e}")
                return False
        else:
            # If no condition is specified, default to True
            return True

    async def _prepare_tool_params(self, ctx: ObservableCtx) -> dict:
        # 根据规则配置和上下文准备工具调用参数
        tool_params = {}
        ctx_keys = self.rule_config.tool_params.get("ctx", [])
        for key in ctx_keys:
            tool_params[key] = ctx.get(key)
        logger.debug(f"Tool params[after ctx]: {tool_params}")
        config_keys = self.rule_config.tool_params.get("config", [])
        for key in config_keys:
            tool_params[key] = self.rule_config.__dict__[key]
        logger.debug(f"Tool params[after config]: {tool_params}")
        extra_params = self.rule_config.tool_params.get("extra", {})
        tool_params.update(extra_params)
        logger.debug(f"Tool params[after extra]: {tool_params}")

        tool_params["ctx"] = ctx
        tool_params["rule_config"] = self.rule_config

        return tool_params

    async def _handle_tool_result(
        self, ctx: ObservableCtx, dispatcher: "RuleDispatcher", response_full: str
    ):
        # 根据规则配置和上下文处理工具调用结果
        if self.rule_config.tool_result_target == "DIRECT_RETURN":
            # save to ctx.dialogue.history
            await ctx.append("dialogue.history", f"A: {response_full}")
        elif self.rule_config.tool_result_target == "AS_CONTEXT":
            await ctx.set(self.rule_config.tool_result_key, response_full)
        elif self.rule_config.tool_result_target == "NEW_RULES":
            # 解析&生成新的规则
            new_rule_configs: List[RuleConfig] = RuleConfig.parse_and_gen(
                source=self.rule_config.name,
                tool_result_full=response_full,
                save=True,
            )
            for new_cfg in new_rule_configs:
                new_cfg.auto_generated = True
                dispatcher.add_new_rule(new_cfg, immediate=True)

    async def _record_metrics(self, execution_time: float, error_occurred: bool):
        """记录任务执行指标"""
        # 这里可以实现指标记录逻辑，如将执行时间、成功/失败状态等记录到监控系统
        pass

    async def _execute_with_retry(self, tool_params: dict) -> AsyncGenerator[str, None]:
        """执行工具调用，带重试逻辑

        Args:
            tool_params: 工具调用参数

        Yields:
            工具执行过程中的输出内容
        """
        max_retries = 2  # 可配置, self.rule_config.max_retries
        retry_count = 0
        last_error = None
        self._response_full = ""
        self._last_error = None

        while retry_count < max_retries:
            try:
                async for chunk in ToolCenter.run_tool(
                    name=self.rule_config.tool, **tool_params
                ):
                    if self.rule_config.tool_result_target == "DIRECT_RETURN":
                        yield chunk
                    self._response_full += chunk

                # 工具执行成功，跳出重试循环
                self._last_error = None
                return

            except asyncio.CancelledError as e:
                # 特殊处理取消操作，不计入重试次数
                logger.warning(f"Task {self.task_id}: Tool execution was cancelled")
                yield "Tool execution was cancelled"
                self._last_error = e
                return

            except (ConnectionError, TimeoutError) as e:
                # 网络或超时错误，可以重试
                retry_count += 1
                last_error = e
                self._last_error = e
                logger.warning(
                    f"Task {self.task_id}: Tool execution failed (attempt {retry_count}/{max_retries}): {e}"
                )
                # 指数退避重试
                await asyncio.sleep(min(2**retry_count, 10))

            except Exception as e:
                # 其他错误，不重试
                logger.error(
                    f"Task {self.task_id}: Tool {self.rule_config.tool} execution failed: {e}"
                )
                yield f"Error: Tool {self.rule_config.tool} execution failed: {e}"
                self._last_error = e
                return

        # 达到最大重试次数
        if retry_count == max_retries and last_error:
            logger.error(
                f"Task {self.task_id}: Tool {self.rule_config.tool} execution failed after {max_retries} attempts: {last_error}"
            )
            yield f"Error: Tool {self.rule_config.tool} execution failed after multiple attempts: {last_error}"
            self._last_error = last_error

    async def _handle_tool_error(
        self, error: Exception, error_context: str = ""
    ) -> str:
        """处理工具执行过程中的错误

        Args:
            error: 错误对象
            error_context: 错误上下文描述

        Returns:
            错误消息
        """
        error_message = ""

        if isinstance(error, asyncio.CancelledError):
            error_message = "Tool execution was cancelled"
        elif isinstance(error, json.JSONDecodeError):
            error_message = f"Failed to process tool result (invalid format): {error}"
        elif isinstance(error, (ConnectionError, TimeoutError)):
            error_message = f"Connection or timeout error: {error}"
        elif error:
            if error_context:
                error_message = f"Error in {error_context}: {error}"
            else:
                error_message = f"Error: {error}"
        else:
            error_message = "Unknown error occurred"

        logger.error(f"Task {self.task_id}: {error_message}")
        return error_message

    async def execute_tool(
        self, ctx: ObservableCtx, dispatcher: "RuleDispatcher"
    ) -> AsyncGenerator[str, None]:
        """
        执行工具调用
        """
        # 记录开始执行时间，用于监控和超时处理
        start_time = time.time()
        error_occurred = False
        self._response_full = ""
        self._last_error = None

        try:
            # 1. 准备工具调用参数
            try:
                tool_params: dict = await self._prepare_tool_params(ctx)
                logger.debug(
                    f"Task {self.task_id}: Tool params prepared: {tool_params}"
                )
            except Exception as e:
                error_occurred = True
                self._last_error = e
                error_msg = await self._handle_tool_error(e, "parameter preparation")
                yield f"Error: Failed to prepare parameters for tool {self.rule_config.tool}: {e}"
                return

            # 2. 执行工具调用（带重试逻辑）
            try:
                # 使用重试逻辑执行工具
                async for chunk in self._execute_with_retry(tool_params):
                    yield chunk

                # 检查执行后的错误状态
                if self._last_error:
                    error_occurred = True
                    return

                # 如果没有错误，处理工具调用结果
                try:
                    await self._handle_tool_result(ctx, dispatcher, self._response_full)
                except json.JSONDecodeError as e:
                    error_occurred = True
                    self._last_error = e
                    error_msg = await self._handle_tool_error(e, "JSON parsing")
                    yield f"Error: {error_msg}"
                except Exception as e:
                    error_occurred = True
                    self._last_error = e
                    error_msg = await self._handle_tool_error(e, "result handling")
                    yield f"Error: Tool {self.rule_config.tool} result handling failed: {e}"
            except Exception as e:
                error_occurred = True
                self._last_error = e
                error_msg = await self._handle_tool_error(e, "tool execution")
                yield f"Error: {error_msg}"

        except Exception as e:
            # 捕获所有未处理的异常
            error_occurred = True
            self._last_error = e
            logger.error(
                f"Task {self.task_id}: Unexpected error in execute_tool: {e}",
                exc_info=True,
            )
            yield f"Error: Unexpected error occurred: {e}"

        finally:
            # 正确设置任务状态，保持一致性
            execution_time = time.time() - start_time
            # 使用新的状态机设置状态
            await self.set_state(
                TaskState.COMPLETED if not error_occurred else TaskState.FAILED,
                success=not error_occurred,
                error=(
                    str(self._last_error)
                    if error_occurred and self._last_error
                    else None
                ),
            )

            # 记录执行结果
            if error_occurred:
                logger.error(
                    f"Task {self.task_id} completed with errors in {execution_time:.2f}s"
                )
            else:
                logger.info(
                    f"Task {self.task_id} completed successfully in {execution_time:.2f}s"
                )

            # 可选：记录性能指标
            await self._record_metrics(execution_time, error_occurred)
