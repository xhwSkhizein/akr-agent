import logging
from typing import TYPE_CHECKING, AsyncGenerator, List
import json
import time
import asyncio
from core.tools.base import ToolCenter

from core.rule_config import RuleConfig
from core.observable_ctx import ObservableCtx

if TYPE_CHECKING:
    from .dispatcher import RuleDispatcher  # Circular import for type hinting

logger = logging.getLogger(__name__)


class RuleTask:
    def __init__(self, rule_config: RuleConfig, task_id: str):
        self.rule_config = rule_config
        self.task_id = task_id
        self._completed = False
        self._success = False  # Was the execution successful?
        self._executing = False  # Is the task currently being executed?

    def is_completed(self) -> bool:
        return self._completed

    def set_completed(self, status: bool, success: bool = True) -> None:
        self._completed = status
        self._success = success
        if status:
            logger.debug(
                f"Task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}) marked as completed. Success: {success}"
            )

    def is_executing(self) -> bool:
        return self._executing

    def set_executing(self, status: bool) -> None:
        self._executing = status

    def is_condition_meet(self, ctx: ObservableCtx) -> bool:
        if self._completed or self._executing:
            logger.debug(
                f"Task {self.task_id} is not ready because it is completed or executing."
            )
            return False  # Don't re-run if completed or already processing

        if self.rule_config.match_condition:
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
                        "len": len,
                        "list": list,
                        "dict": dict,
                        "in": lambda item, container: item in container,
                    }
                }
                eval_locals = {"ctx": ctx}  # ctx object itself, allowing ctx.get('key')

                # Make sure that when the condition is written, it accesses ctx via ctx.get('pk.sk.some_key')
                # or checks for key existence with `'pk.sk.some_key' in ctx`
                condition_met = bool(
                    eval(self.rule_config.match_condition, eval_globals, eval_locals)
                )
                logger.debug(
                    f"Task {self.task_id} condition '{self.rule_config.match_condition}' evaluated to: {condition_met}"
                )
                return condition_met
            except Exception as e:
                logger.warning(
                    f"Error evaluating match_condition for task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}): {e}. Condition: '{self.rule_config.match_condition}'"
                )
                return False
        return False  # Default to not ready if not forced and no condition

    async def _prepare_tool_params(self, ctx: ObservableCtx) -> dict:
        # 根据规则配置和上下文准备工具调用参数
        tool_params = {}
        ctx_keys = self.rule_config.tool_params.get("ctx", [])
        for key in ctx_keys:
            tool_params[key] = ctx.get(key)
        logger.info(f"Tool params[after ctx]: {tool_params}")
        config_keys = self.rule_config.tool_params.get("config", [])
        for key in config_keys:
            tool_params[key] = self.rule_config.__dict__[key]
        logger.info(f"Tool params[after config]: {tool_params}")
        extra_params = self.rule_config.tool_params.get("extra", {})
        tool_params.update(extra_params)
        logger.info(f"Tool params[after extra]: {tool_params}")

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

    async def execute_tool(
        self, ctx: ObservableCtx, dispatcher: "RuleDispatcher"
    ) -> AsyncGenerator[str, None]:
        """
        执行工具调用
        """
        # 记录开始执行时间，用于监控和超时处理
        start_time = time.time()
        error_occurred = False
        response_full = ""

        try:
            # 1. 准备工具调用参数
            try:
                tool_params: dict = await self._prepare_tool_params(ctx)
                logger.info(f"Task {self.task_id}: Tool params prepared: {tool_params}")
            except Exception as e:
                logger.error(
                    f"Task {self.task_id}: Failed to prepare tool parameters: {e}"
                )
                error_occurred = True
                yield f"Error: Failed to prepare parameters for tool {self.rule_config.tool}: {e}"
                return

            # 2. 执行工具调用（带重试逻辑）
            max_retries = 2  # 可配置, self.rule_config.max_retries
            retry_count = 0
            last_error = None

            while retry_count < max_retries:
                try:
                    async for chunk in ToolCenter.run_tool(
                        name=self.rule_config.tool, **tool_params
                    ):
                        if self.rule_config.tool_result_target == "DIRECT_RETURN":
                            yield chunk
                        response_full += chunk

                    # 工具执行成功，跳出重试循环
                    break

                except asyncio.CancelledError:
                    # 特殊处理取消操作，不计入重试次数
                    logger.warning(f"Task {self.task_id}: Tool execution was cancelled")
                    error_occurred = True
                    yield f"Tool execution was cancelled"
                    return

                except (ConnectionError, TimeoutError) as e:
                    # 网络或超时错误，可以重试
                    retry_count += 1
                    last_error = e
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
                    error_occurred = True
                    yield f"Error: Tool {self.rule_config.tool} execution failed: {e}"
                    return

            # 检查是否达到最大重试次数
            if retry_count == max_retries:
                logger.error(
                    f"Task {self.task_id}: Tool {self.rule_config.tool} execution failed after {max_retries} attempts: {last_error}"
                )
                error_occurred = True
                yield f"Error: Tool {self.rule_config.tool} execution failed after multiple attempts: {last_error}"
                return

            # 3. 处理工具调用结果
            try:
                await self._handle_tool_result(ctx, dispatcher, response_full)
            except json.JSONDecodeError as e:
                # 特殊处理JSON解析错误
                logger.error(
                    f"Task {self.task_id}: Failed to parse tool result as JSON: {e}"
                )
                error_occurred = True
                yield f"Error: Failed to process tool result (invalid format): {e}"
            except Exception as e:
                logger.error(
                    f"Task {self.task_id}: Tool {self.rule_config.tool} result handling failed: {e}"
                )
                error_occurred = True
                yield f"Error: Tool {self.rule_config.tool} result handling failed: {e}"

        except Exception as e:
            # 捕获所有未处理的异常
            logger.error(
                f"Task {self.task_id}: Unexpected error in execute_tool: {e}",
                exc_info=True,
            )
            error_occurred = True
            yield f"Error: Unexpected error occurred: {e}"

        finally:
            # 正确设置任务状态，保持一致性
            execution_time = time.time() - start_time
            self.set_completed(True, success=not error_occurred)
            self.set_executing(False)

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
