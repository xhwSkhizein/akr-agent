"""
OpenAI LLM 客户端实现
"""

import logging
from typing import Any, AsyncGenerator, Dict, Optional

from openai import AsyncOpenAI

from .base import LLMClient


class OpenAIClient(LLMClient):
    """
    OpenAI API 客户端实现
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        """
        初始化 OpenAI 客户端

        Args:
            api_key: OpenAI API 密钥，如果为 None 则使用环境变量
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大令牌数
            **kwargs: 其他 OpenAI API 参数
        """
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_params = kwargs
        logging.info(f"初始化 OpenAI 客户端，模型: {model}")

    async def invoke_stream(
        self, system_prompt: str, user_input: str, **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        流式调用 OpenAI API 并返回响应流

        Args:
            prompt: 提示词
            **kwargs: 覆盖默认参数

        Yields:
            响应片段
        """
        params = self._prepare_params(system_prompt, user_input, **kwargs)
        params["stream"] = True

        try:
            logging.debug(f"OPENAI final request params: {params}")
            response_stream = await self.client.chat.completions.create(**params)

            async for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logging.error(f"OpenAI API 流式调用失败: {e}")
            yield f"错误: {str(e)}"

    def _prepare_params(
        self, system_prompt: str, prompt: str, **kwargs
    ) -> Dict[str, Any]:
        """
        准备 API 调用参数

        Args:
            prompt: 提示词
            **kwargs: 覆盖默认参数

        Returns:
            API 调用参数字典
        """
        # 基本参数
        params = {
            "model": kwargs.get("model", self.model),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }

        # 添加可选参数
        if self.max_tokens is not None:
            params["max_tokens"] = kwargs.get("max_tokens", self.max_tokens)

        # 添加额外参数
        for key, value in self.extra_params.items():
            if key not in params:
                params[key] = kwargs.get(key, value)

        # 添加系统提示词（如果提供）
        system_prompt = kwargs.get("system_prompt")
        if system_prompt:
            params["messages"].insert(0, {"role": "system", "content": system_prompt})

        return params
