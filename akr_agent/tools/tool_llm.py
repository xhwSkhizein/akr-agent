import logging
import os

logger = logging.getLogger(__name__)

from typing import Any, AsyncGenerator, Dict, List
from jinja2 import Environment, select_autoescape, TemplateError

# Setup Jinja2 environment
# You might want to move this to a more central place if used elsewhere
jinja_env = Environment(
    loader=None,  # We'll load templates from strings
    autoescape=select_autoescape(["html", "xml"]),  # Basic autoescaping
)

from ..context_manager import ObservableCtx
from ..rule_config import RuleConfig
from ..llm.openai_client import OpenAIClient
from .base import Tool, ToolCenter


class LLMCallTool(Tool):
    """
    LLM Call Tool, used to call LLM

    Supported parameters:
    - system_prompt: System prompt
    - prompt: Prompt
    - prompt_detail: Prompt detail
    - ctx: Observable context
    - rule_config: Rule config
    - extra: Extra config
        - tools: Tool list
    """

    def __init__(self, **kwargs):
        # FIXME support build any kind of LLM clients
        self.llm_client = OpenAIClient(
            model=kwargs.get("model", "gpt4o-mini"),
            api_key=kwargs.get("api_key", os.environ.get("OPENAI_API_KEY")),
            base_url=kwargs.get("base_url", "https://api.openai.com"),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 1024),
            stream=kwargs.get("stream", True),
        )

    async def run(
        self,
        user_input: str,
        system_prompt: str,
        prompt: str,
        prompt_detail: str,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """Execute LLM call

        Args:
            user_input: User input, the content of user input when calling LLM
            system_prompt: The most important system prompt, defining the goal, requirements, constraints, and expected output
            prompt: Prompt, used to supplement system prompt, strengthening key points
            prompt_detail: Detailed explanation, guidance, etc. for key points, encouraging the model to perform inference steps, add examples, or standardize output format before reaching a conclusion
            **kwargs: Other parameters
        """
        system_prompt = await self._render_prompt(
            system_prompt=system_prompt,
            prompt=prompt,
            prompt_detail=prompt_detail,
            **kwargs,
        )

        logger.debug(f"llm tool call, kwargs={kwargs}")

        tool_defs = await self._build_tool_defs(**kwargs)

        async for chunk in self.llm_client.invoke_stream(
            system_prompt=system_prompt,
            user_input=user_input,
            messages=[],
            run_tool_func=ToolCenter.run_tool,
            tools=tool_defs,
            ctx_manager=kwargs.get("ctx_manager"),
        ):
            yield chunk

    async def _render_prompt(
        self, system_prompt: str, prompt: str, prompt_detail: str, **kwargs
    ) -> str:
        # Ensure system_prompt is not None
        if system_prompt is None:
            system_prompt = ""

        if not (prompt or prompt_detail):
            return system_prompt

        if prompt:
            system_prompt = system_prompt + "\n\n" + prompt
        if prompt_detail:
            system_prompt += "\n\n" + prompt_detail

        ctx: ObservableCtx = kwargs.get("ctx")
        rule_config: RuleConfig = kwargs.get("rule_config")

        if not ctx:
            return system_prompt

        custom_render_ctx = (
            {k: ctx.get(k) for k in rule_config.depend_ctx_key}
            if rule_config.depend_ctx_key
            else ctx.to_dict()
        )
        try:
            template = jinja_env.from_string(system_prompt)
            system_prompt = template.render(**custom_render_ctx)
        except TemplateError as e:
            logger.error(f"Template rendering error: {e}", exc_info=True)
            # Downgrade strategy: return unrendered prompt
            system_prompt = system_prompt + "\n\n[Note: Template rendering failed]"
        except Exception as e:
            logger.error(
                f"Error rendering prompt template for rule: {rule_config.name}: {e}"
            )

        return system_prompt

    async def _build_tool_defs(self, **kwargs) -> List[Dict[str, Any]]:
        tool_defs = []
        config_tool_names: List[str] = kwargs.get("tools", [])
        logger.debug(f"tool exec depends tools={config_tool_names}")
        if not config_tool_names or len(config_tool_names) == 0:
            return tool_defs
        for tool_name in config_tool_names:
            tool_def = ToolCenter.get_definition(name=tool_name)
            if tool_def:
                tool_defs.append({"type": "function", "function": tool_def})
                logger.debug(f"Use tool: {tool_name} {tool_defs}")
            else:
                logger.warning(f"Cannot get tool: {tool_name}, def={tool_def}")

        return tool_defs
