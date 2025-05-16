"""
OpenAI LLM 客户端实现
"""

import logging

logger = logging.getLogger(__name__)

from typing import Any, AsyncGenerator, Dict, Optional
import openai
import asyncio
from openai import AsyncOpenAI
from openai.types.chat.chat_completion import ChatCompletion

from .base import LLMClient


class OpenAIClient(LLMClient):
    """
    OpenAI API 客户端实现
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
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

        max_retries = 3
        retry_count = 0
        backoff_factor = 2

        while retry_count <= max_retries:
            try:
                logging.debug(f"OPENAI final request params: {params}")
                response_stream: AsyncGenerator[ChatCompletion, None] = (
                    await self.client.chat.completions.create(**params)
                )
                # 2. 处理流
                function_call_buffer = {}
                collecting_function_call = False
                async for chunk in response_stream:
                    delta = chunk.choices[0].delta

                    # 2.1 处理 function_call
                    if hasattr(delta, "function_call") and delta.function_call:
                        collecting_function_call = True
                        for k, v in delta.function_call.items():
                            function_call_buffer[k] = (
                                function_call_buffer.get(k, "") + v
                            )

                        # function_call 结束条件：arguments 字段已完整
                        if (
                            "name" in function_call_buffer
                            and "arguments" in function_call_buffer
                            and delta.function_call.get("arguments") is not None
                        ):
                            # 2.2 工具调用
                            tool_name = function_call_buffer["name"]
                            tool_args = function_call_buffer["arguments"]
                            logger.info(f"开始调用工具: {tool_name}, 参数: {tool_args}")
                            run_tool_func = kwargs.get("run_tool_func")
                            tool_result = await run_tool_func(tool_name, tool_args)
                            logger.info(
                                f"工具 name:{tool_name}, args: {tool_args} 调用结果: {tool_result}"
                            )
                            # 2.3 把工具结果作为新的 message 继续对话
                            params["messages"].append(
                                {
                                    "role": "assistant",
                                    "content": None,
                                    "function_call": {
                                        "name": tool_name,
                                        "arguments": tool_args,
                                    },
                                }
                            )
                            params["messages"].append(
                                {
                                    "role": "function",
                                    "name": tool_name,
                                    "content": str(tool_result),
                                }
                            )
                            # 递归调用自身，继续流式输出
                            async for content in self.invoke_stream(
                                system_prompt, user_input, **params
                            ):
                                yield content
                            return  # 结束本轮
                    elif hasattr(delta, "content") and delta.content:
                        # 普通内容流式输出
                        yield delta.content
                # 3. 如果没有 function_call，直接结束
                if collecting_function_call and function_call_buffer:
                    # 可能 function_call 没有完整返回
                    yield f"[Function call incomplete: {function_call_buffer}]"

            except openai.RateLimitError as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"Rate limit exceeded. Retrying in {wait_time}s. Attempt {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    yield f"错误: API速率限制超出，请稍后再试。"

            except openai.AuthenticationError:
                logger.error("OpenAI API认证失败，请检查API密钥")
                yield "错误: API认证失败，请检查API密钥配置。"
                break

            except (openai.APIConnectionError, asyncio.TimeoutError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"连接错误: {e}. 将在{wait_time}秒后重试. 尝试 {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    yield f"错误: 连接OpenAI API失败: {e}"

            except asyncio.CancelledError:
                logger.info("OpenAI API请求被取消")
                break

            except Exception as e:
                logger.error(f"OpenAI API调用未预期错误: {e}", exc_info=True)
                yield f"错误: {str(e)}"
                break
            # 如果没有异常，退出重试循环
            break

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
            "tools": kwargs.get("tools", []),
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
