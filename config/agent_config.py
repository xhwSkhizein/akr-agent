from typing import List
from pydantic import BaseModel
from config.rule_config import AgentMeta, RuleConfig


class AgentConfig(BaseModel):
    name: str
    meta: AgentMeta
    system_prompt: str
    rules: List[RuleConfig]


class LLMConfig(BaseModel):
    api_key: str
    model: str = "gpt4o-mini"
    temperature: float = 0.0
    max_tokens: int = 1024
    stream: bool = True
    # 其他可选参数……
