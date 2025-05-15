"""
LLM 模块 - 提供 LLM 客户端接口和实现
"""

from .base import LLMClient, LLMResponse
from .openai_client import OpenAIClient

__all__ = ["LLMClient", "LLMResponse", "OpenAIClient"]
