import logging
from typing import TYPE_CHECKING, AsyncGenerator

from jinja2 import Environment, select_autoescape


# Setup Jinja2 environment
# You might want to move this to a more central place if used elsewhere
jinja_env = Environment(
    loader=None,  # We'll load templates from strings
    autoescape=select_autoescape(["html", "xml"]),  # Basic autoescaping
)

from config.rule_config import RuleConfig
from core.observable_ctx import ObservableCtx
from llm.base import LLMClient

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

    async def execute(
        self,
        ctx: ObservableCtx,
        dispatcher: "RuleDispatcher",
        llm_client: LLMClient,
        base_system_prompt: str,
        user_input_for_llm: str,  # This is ctx.get('user_input') passed for convenience
    ) -> AsyncGenerator[str, None]:
        """
        Executes the rule.
        Yields string chunks for DIRECT_RETURN rules.
        Can update ctx or add new rules via the dispatcher.
        """
        logger.debug(
            f"Executing task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}). Target: {self.rule_config.ai_response_target}"
        )

        # 1. Prepare prompt using Jinja2 template
        dep_ctx_dict = {k: ctx.get(k) for k in self.rule_config.depend_ctx_key}

        full_prompt_str = self.rule_config.prompt
        if self.rule_config.prompt_detail:
            full_prompt_str += "\n\n" + self.rule_config.prompt_detail

        try:
            template = jinja_env.from_string(full_prompt_str)
            rendered_rule_prompt = template.render(**dep_ctx_dict)
        except Exception as e:
            logger.error(
                f"Error rendering prompt template for task {self.task_id}: {e}"
            )
            self.set_completed(True, success=False)
            yield f"Error: Prompt rendering failed for rule related to: {self.rule_config.name if hasattr(self.rule_config, 'name') else self.task_id}"
            return  # Stop execution if prompt fails

        final_system_prompt = base_system_prompt + "\n\n" + rendered_rule_prompt
        logger.debug(f"Final system prompt: {final_system_prompt}")

        # 2. Call LLM (if prompt is not empty - some rules might just be for ctx manipulation or flow control)
        llm_response_full = ""
        if (
            rendered_rule_prompt.strip()
        ):  # Only call LLM if there is a substantial prompt
            try:
                async for chunk in llm_client.invoke_stream(
                    system_prompt=final_system_prompt,
                    user_input=user_input_for_llm,  # The original user input is the main prompt to LLM here
                ):
                    if self.rule_config.ai_response_target == "DIRECT_RETURN":
                        yield chunk
                    llm_response_full += chunk
            except Exception as e:
                logger.error(
                    f"LLM call failed for task {self.task_id}: {e}", exc_info=True
                )
                self.set_completed(True, success=False)
                # Optionally, yield an error message to the user for DIRECT_RETURN rules
                if self.rule_config.ai_response_target == "DIRECT_RETURN":
                    yield f"Error: LLM interaction failed for: {self.rule_config.name if hasattr(self.rule_config, 'name') else self.task_id}. Please check logs."
                return  # Stop if LLM fails
        else:
            logger.debug(
                f"Skipping LLM call for task {self.task_id} as rendered rule prompt is empty."
            )

        # 3. Process LLM response
        if self.rule_config.ai_response_target == "AS_CONTEXT":
            if self.rule_config.ai_response_key:
                await ctx.set(self.rule_config.ai_response_key, llm_response_full)
                logger.debug(
                    f"Task {self.task_id} stored LLM response in ctx key '{self.rule_config.ai_response_key}'"
                )
            else:
                logger.warning(
                    f"Task {self.task_id} is AS_CONTEXT but no ai_response_key is defined."
                )
        elif self.rule_config.ai_response_target == "NEW_RULES":
            # 4. Handle dynamic rule generation (example, needs defining in RuleConfig)
            new_rule_configs = RuleConfig.create_from(llm_response_full)
            for new_cfg in new_rule_configs:
                logger.debug(f"Task {self.task_id} generated new rule: {new_cfg.name}")
                dispatcher.add_new_rule(new_cfg, immediate=True)
        elif self.rule_config.ai_response_target == "DIRECT_RETURN":
            # 将 AI 的回复保存到上下文中
            await ctx.append("dialogue.history", f"A: {llm_response_full}")

        # 5. Mark task as completed
        self.set_completed(True, success=True)  # Mark as completed successfully
        logger.debug(
            f"Task {self.task_id} (Name: {self.rule_config.name if hasattr(self.rule_config, 'name') else 'N/A'}) finished execution."
        )

        # Ensure an empty yield if this was a DIRECT_RETURN and loop finished, or if it wasn't DIRECT_RETURN
        # This satisfies the AsyncGenerator type hint if no chunks were yielded.
        if False:  # Logic to make this a generator even if no yield occurred above
            yield
