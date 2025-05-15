import logging
from typing import TYPE_CHECKING, AsyncGenerator, List

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

    async def execute_tool(
        self, ctx: ObservableCtx, dispatcher: "RuleDispatcher"
    ) -> AsyncGenerator[str, None]:
        """
        执行工具调用
        """
        # 1. 准备工具调用参数
        tool_params: dict = await self._prepare_tool_params(ctx)
        logger.info(f"Tool params[after prepare]: {tool_params}")

        # 2. 执行工具调用
        response_full = ""
        try:
            async for chunk in ToolCenter.run_tool(
                name=self.rule_config.tool, **tool_params
            ):
                if self.rule_config.tool_result_target == "DIRECT_RETURN":
                    yield chunk
                response_full += chunk
        except Exception as e:
            logger.error(f"Tool {self.rule_config.tool} execution failed: {e}")
            self.set_completed(True, success=False)
            yield f"Error: Tool {self.rule_config.tool} execution failed: {e}"
            return

        # 3. 处理工具调用结果
        try:
            await self._handle_tool_result(ctx, dispatcher, response_full)
        except Exception as e:
            logger.error(f"Tool {self.rule_config.tool} result handling failed: {e}")
            self.set_completed(True, success=False)
            yield f"Error: Tool {self.rule_config.tool} result handling failed: {e}"
            return
        finally:
            self.set_completed(True, success=True)
            logger.info(
                f"Task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}) finished execution."
            )
        # Ensure an empty yield if this was a DIRECT_RETURN and loop finished, or if it wasn't DIRECT_RETURN
        # This satisfies the AsyncGenerator type hint if no chunks were yielded.
        if False:  # Logic to make this a generator even if no yield occurred above
            yield
