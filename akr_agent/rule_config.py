import json
import os
import time
import logging

from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AgentMeta(BaseModel):
    name: str
    desc: str
    parameters: Optional[Dict[str, Any]] = None


def save_rule_config(source: str, rule_config: "RuleConfig"):
    # 保存到文件中
    # 文件名：<source>_generated_<name>_<timestamp>.json
    # 文件内容：rule_config.model_dump_json()
    # 文件路径：logs/rule_configs/
    # 文件夹不存在时创建
    os.makedirs("logs/rule_configs", exist_ok=True)
    with open(
        f"logs/rule_configs/{source}_generated_{rule_config.name}_{time.strftime('%Y%m%d_%H%M%S')}.json",
        "w",
    ) as f:
        f.write(rule_config.model_dump_json())


def find_json_in_str(s: str) -> str:
    # 从字符串中找到第一个 JSON 对象
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1:
        return s[start : end + 1]
    return None


class RuleConfig(BaseModel):
    """
    规则配置

    Parameters:
        name: 规则名称
        depend_ctx_key: 需要从上下文中获取的数据对应的 key
        match_condition: 需要满足的条件, 会被 eval 执行,
                        例如："力量训练" in ctx.get("intent_analysis_result.intent")

        prompt: 此规则的定制 prompt（会拼接到 system_prompt 后面）
        prompt_detail: 规则的更多补充 prompt 信息，同样拼接在 system_prompt + prompt 后面

        tool: 执行的工具调用名称
        tool_params: 需要用到的 tools 的参数
                    ```json
                    {
                        "ctx": ["user_input"], # 动态的、由其他 Rule 或者 Agent 生成
                        "config": ["prompt", "prompt_detail"], # 固定的配置
                        "extra": {}, # 额外的常量
                    }
                    ```
        tool_result_target: 此规则 ai 输出的结果输出到哪里：\n
                            - AS_CONTEXT 存储到上下文中
                            - DIRECT_RETURN 直接返回给用户
                            - NEW_RULES 生成新的规则
        tool_result_key: 如果是 AS_CONTEXT，整个 AI 返回的 JSON 使用下面的 key 保存进 ctx 中
        auto_generated: 是否是自动生成的规则
        priority: 优先级
    """

    name: str
    depend_ctx_key: List[str]
    match_condition: Optional[str] = None

    prompt: str
    prompt_detail: Optional[str] = ""

    tool: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = {}
    tool_result_target: Literal["AS_CONTEXT", "DIRECT_RETURN", "NEW_RULES"]
    tool_result_key: Optional[str] = None
    auto_generated: bool = False
    priority: int = 0

    @classmethod
    def parse_and_gen(
        cls, source: str, tool_result_full: str, save: bool = False
    ) -> List["RuleConfig"]:
        # 解析 llm_response_full 并生成新的规则
        try:
            # 尝试直接解析完整JSON
            json_data = json.loads(tool_result_full, strict=False)
        except json.JSONDecodeError:
            # 尝试从文本中提取JSON
            try:
                json_str = find_json_in_str(tool_result_full)
                if not json_str:
                    logger.error(f"无法从结果中提取JSON: {tool_result_full[:100]}...")
                    return []

                json_data = json.loads(json_str, strict=False)
            except json.JSONDecodeError as e:
                logger.error(
                    f"JSON解析失败: {e}, 原始内容: {tool_result_full[:100]}..."
                )
                return []
        result = []
        try:
            if isinstance(json_data, list):
                result = [cls(**item) for item in json_data]
            elif isinstance(json_data, dict):
                result = [cls(**json_data)]
            else:
                raise ValueError(f"Invalid JSON data: {tool_result_full}")
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid JSON data: {tool_result_full}")
            return []

        if save and len(result) > 0:
            for rule_config in result:
                save_rule_config(source=source, rule_config=rule_config)

        return result


class AgentConfig(BaseModel):
    name: str
    meta: AgentMeta
    system_prompt: str
    rules: List[RuleConfig]
    max_concurrent_tasks: int = 1
    timeout_detection_time: int = 60
    
