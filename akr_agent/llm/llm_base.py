from dataclasses import dataclass
from typing import Any
from dataclasses_json import DataClassJsonMixin
from typing import Literal


import logging

logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass
class ToolCallParameters:
    tool_call_id: str
    tool_name: str
    tool_input: Any


@dataclass
class ToolParam(DataClassJsonMixin):
    """Internal representation of LLM tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall(DataClassJsonMixin):
    """Internal representation of LLM-generated tool call."""

    tool_call_id: str
    tool_name: str
    tool_input: Any


@dataclass
class ToolResult(DataClassJsonMixin):
    """Internal representation of LLM tool result."""

    tool_call_id: str
    tool_name: str
    tool_output: Any


@dataclass
class ToolFormattedResult(DataClassJsonMixin):
    """Internal representation of formatted LLM tool result."""

    tool_call_id: str
    tool_name: str
    tool_output: list[dict[str, Any]] | str


@dataclass
class TextPrompt(DataClassJsonMixin):
    """Internal representation of user-generated text prompt."""

    text: str
    role: Literal["user", "assistant"] = "user"


@dataclass
class ImageBlock(DataClassJsonMixin):
    type: Literal["image"]
    source: dict[str, Any]
    role: Literal["assistant"] = "assistant"


@dataclass
class AIContext(DataClassJsonMixin):
    """Internal representation of LLM-generated middle result."""

    context: str
    role: Literal["assistant"] = "assistant"


@dataclass
class TextResult(DataClassJsonMixin):
    """Internal representation of LLM-generated text result."""

    text: str
    role: Literal["assistant"] = "assistant"


# agent内容块
AssistantContentBlock = TextResult | ToolCall | AIContext

# 用户内容块
UserContentBlock = TextPrompt | ToolFormattedResult

# 通用内容块
GeneralContentBlock = UserContentBlock | AssistantContentBlock

# LLM 消息
LLMMessages = list[list[GeneralContentBlock]]

