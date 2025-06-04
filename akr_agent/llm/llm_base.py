# Copy from https://github.com/Intelligent-Internet/ii-agent

from dataclasses import dataclass
from typing import Any, Optional
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


@dataclass
class TokenUsage(DataClassJsonMixin):
    """Internal representation of LLM token usage."""
    model: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    completion_tokens_details: Optional[dict[str, Any]]
    prompt_tokens_details: Optional[dict[str, Any]]
    role: Literal["user", "assistant"] = "assistant"


# agent content block
AssistantContentBlock = TextResult | ToolCall | AIContext | TokenUsage

# user content block
UserContentBlock = TextPrompt | ToolFormattedResult

# general content block
GeneralContentBlock = UserContentBlock | AssistantContentBlock

# LLM messages
LLMMessages = list[list[GeneralContentBlock]]

