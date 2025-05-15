import logging
import os

logger = logging.getLogger(__name__)

from typing import Any, AsyncGenerator, Dict, List
from jinja2 import Environment, select_autoescape

# Setup Jinja2 environment
# You might want to move this to a more central place if used elsewhere
jinja_env = Environment(
    loader=None,  # We'll load templates from strings
    autoescape=select_autoescape(["html", "xml"]),  # Basic autoescaping
)

from core.rule_config import RuleConfig
from core.observable_ctx import ObservableCtx
from core.llm.openai_client import OpenAIClient
from core.tools.base import Tool, ToolCenter


class LLMCallTool(Tool):
    """
    LLM 调用工具

    支持的参数:
    - system_prompt: 系统提示
    - prompt: 提示
    - prompt_detail: 提示详情
    - ctx: 上下文
    - rule_config: 规则配置
    - extra: 额外配置
        - tools: 工具列表
    """

    def __init__(self, **kwargs):
        # FIXME support build any kind of LLM clients
        self.llm_client = OpenAIClient(
            model=kwargs.get("model", "gpt4o-mini"),
            api_key=kwargs.get("api_key", os.environ.get("OPENAI_API_KEY")),
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
        """执行 LLM 调用

        Args:
            user_input: 用户输入, 调用 LLM 时用户输入的内容
            system_prompt: 最主要的系统提示，定义了目标、需求、约束和预期输出
            prompt: 提示补充，用于补充系统提示，针对关键点进行加强
            prompt_detail: 对于关键点的详细说明、引导等，鼓励模型在得出结论前进行推理步骤、增加示例或规范输出格式等
            **kwargs: 其他参数
        """
        system_prompt = await self._render_prompt(
            system_prompt=system_prompt,
            prompt=prompt,
            prompt_detail=prompt_detail,
            **kwargs,
        )
        tool_defs = await self._build_tool_defs(**kwargs)

        async for chunk in self.llm_client.invoke_stream(
            system_prompt=system_prompt,
            user_input=user_input,
            tools=tool_defs,
            run_tool_func=ToolCenter.run_tool,
        ):
            yield chunk

    async def _render_prompt(
        self, system_prompt: str, prompt: str, prompt_detail: str, **kwargs
    ) -> str:
        if prompt or prompt_detail:
            if prompt:
                system_prompt = system_prompt + "\n\n" + prompt
            if prompt_detail:
                system_prompt += "\n\n" + prompt_detail

            ctx: ObservableCtx = kwargs.get("ctx")
            rule_config: RuleConfig = kwargs.get("rule_config")
            custom_render_ctx = {k: ctx.get(k) for k in rule_config.depend_ctx_key}
            try:
                template = jinja_env.from_string(system_prompt)
                system_prompt = template.render(**custom_render_ctx)
            except Exception as e:
                logger.error(
                    f"Error rendering prompt template for task {self.task_id}: {e}"
                )
                system_prompt = system_prompt + "\n\n" + prompt

        return system_prompt

    async def _build_tool_defs(self, **kwargs) -> List[Dict[str, Any]]:
        tool_defs = []
        extra: Dict[str, Any] = kwargs.get("extra", {})
        config_tool_names: List[str] = extra.get("tools", [])
        if len(config_tool_names) == 0:
            return tool_defs
        for tool_name in config_tool_names:
            tool_def = ToolCenter.get_definition(tool_name)
            if tool_def:
                tool_defs.append(tool_def)
        logger.info(f"根据 extra 配置，获取到可使用的工具: {tool_defs}")

        return tool_defs
