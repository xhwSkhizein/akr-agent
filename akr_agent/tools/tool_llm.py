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
        # 确保system_prompt不为None
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
            logger.error(f"模板渲染错误: {e}", exc_info=True)
            # 降级策略：返回未渲染的提示
            system_prompt = system_prompt + "\n\n[注意: 模板渲染失败]"
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
                logger.debug(f"根据 extra 配置，获取到可使用的工具: {tool_name} {tool_defs}")
            else:
                logger.warning(f"根据 extra 配置，无法获取到对应的 tools={tool_name}, def={tool_def}")

        return tool_defs
