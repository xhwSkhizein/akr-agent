import json
from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel


class AgentMeta(BaseModel):
    name: str
    desc: str
    parameters: Optional[Dict[str, Any]] = None


def find_json_in_str(self, s: str) -> str:
    # 从字符串中找到第一个 JSON 对象
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1:
        return s[start : end + 1]
    return None


class RuleConfig(BaseModel):
    name: str
    # 需要从上下文中获取的数据对应的 key
    depend_ctx_key: List[str]
    # 需要满足的条件, 会被 eval 执行
    # 例如："力量训练" in ctx.get("intent_analysis_result.intent")
    match_condition: Optional[str] = None

    # 下面的 prompt 会根据 depend_ctx_key 使用 jinja2 模版引擎进行渲染
    # 此规则的 prompt（会拼接到 system_prompt 后面）
    prompt: str
    # 此规则 的详细 prompt 信息，同样拼接在 system_prompt 后面
    prompt_detail: Optional[str] = ""

    # 需要用到的 tools
    depend_tools: Optional[List[str]] = []
    # 此规则 ai 输出的结果输出到哪里：as_contenxt 存储到上下文中，
    ai_response_target: Literal["AS_CONTEXT", "DIRECT_RETURN", "NEW_RULES"]
    # 如果是 AS_CONTEXT，整个 AI 返回的 JSON 使用下面的 key 保存进 ctx 中
    ai_response_key: Optional[str] = None

    @classmethod
    def create_from(cls, llm_response_full: str) -> List["RuleConfig"]:
        # 解析 llm_response_full 并生成新的规则
        try:
            json_data = json.loads(llm_response_full, strict=False)
        except json.JSONDecodeError as e:
            json_data = json.loads(find_json_in_str(llm_response_full), strict=False)
            if json_data is None:
                raise ValueError(f"Invalid JSON data: {llm_response_full}")
        if isinstance(json_data, list):
            return [cls(**item) for item in json_data]
        elif isinstance(json_data, dict):
            return [cls(**json_data)]
        else:
            raise ValueError(f"Invalid JSON data: {llm_response_full}")
