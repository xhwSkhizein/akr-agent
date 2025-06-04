"""
OpenAI LLM 客户端实现
"""

import logging
import asyncio
from typing import Any, AsyncGenerator, Dict, Optional, List, Callable
import json
import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
)

from .base import LLMClient
from .llm_base import ToolCall, ToolResult



logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """
    OpenAI API 客户端实现 (支持 tool_calls)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",  # 建议使用支持工具调用的较新模型
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
            **kwargs: 其他 OpenAI API 参数 (例如 base_url, timeout 等)
        """
        self.client = AsyncOpenAI(
            api_key=api_key, **kwargs.pop("client_args", {})
        )  # 传递 client 的额外参数
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_params = kwargs  # 其他传递给 completions.create 的参数
        logging.info(f"初始化 OpenAI 客户端，模型: {model}")

    async def invoke_stream(
        self,
        system_prompt: str,
        user_input: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        run_tool_func: Optional[Callable[[str, str], Any]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        流式调用 OpenAI API 并返回响应流，支持工具调用。

        Args:
            system_prompt: 系统提示词 (仅在初次调用或 messages 为 None 时用于构建初始消息)
            user_input: 用户输入 (仅在初次调用或 messages 为 None 时用于构建初始消息)
            messages: 可选的，预设的消息列表。如果提供，则忽略 system_prompt 和 user_input 来构建初始消息。
            run_tool_func: 可选的异步函数，用于执行工具调用。签名应为: async def run_tool(tool_name: str, tool_args: str) -> Any
            **kwargs: 覆盖默认参数或传递额外参数 (如 tools, tool_choice)
                - ctx_manager: 上下文管理器，用于输出助手消息

        Yields:
            响应片段 (str)
        """
        current_messages: List[Dict[str, Any]]
        if messages is not None:
            current_messages = list(messages)  # 使用提供的消息列表副本
        else:
            current_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]

        # 准备 API 调用参数
        # 注意：kwargs 传递给 _prepare_params，它会合并实例属性和这些运行时参数
        api_params = self._prepare_params(
            system_prompt=system_prompt,  # 传递以备 _prepare_params 可能的初始构建逻辑
            prompt=user_input,  # 同上
            current_messages=current_messages,  # 最重要：传递当前消息历史
            **kwargs,  # 包含 tools, tool_choice 等
        )
        api_params["stream"] = True
        if "ctx_manager" in kwargs:
            from ..context_manager import ContextManager
            ctx_manager: ContextManager = kwargs.get("ctx_manager")
        else:
            ctx_manager = None

        max_retries = 3
        retry_count = 0
        backoff_factor = 2

        while retry_count <= max_retries:
            try:
                logging.debug(f"OPENAI 请求参数: {api_params}")
                response_stream: AsyncGenerator[ChatCompletionChunk, None] = (
                    await self.client.chat.completions.create(**api_params)
                )

                # 用于累积当前LLM响应中的 tool_calls 数据
                # key: tool_call_id, value: {"id": ..., "type": "function", "function_name": ..., "function_arguments": ...}
                active_tool_calls_data: Dict[str, Dict[str, str]] = {}
                tool_calls = []
                # 用于累积本轮LLM回复的文本内容 (如果LLM在要求工具调用前有说话)
                # current_assistant_content_parts: List[str] = []

                async for chunk in response_stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    # 1. 处理普通文本内容流
                    if delta and delta.content:
                        # current_assistant_content_parts.append(delta.content)
                        yield delta.content

                    # 2. 处理 tool_calls 块
                    if delta and delta.tool_calls:
                        tc_chunk_list = delta.tool_calls
                        for tc_chunk in tc_chunk_list:
                            logger.debug(f"PROCESS TOOL CALL CHUNK, {tc_chunk}")
                            if len(tool_calls) <= tc_chunk.index:
                                tool_calls.append(
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                )
                            tc = tool_calls[tc_chunk.index]

                            if tc_chunk.id:
                                tc["id"] += tc_chunk.id
                            if tc_chunk.function.name:
                                tc["function"]["name"] += tc_chunk.function.name
                            if tc_chunk.function.arguments:
                                tc["function"][
                                    "arguments"
                                ] += tc_chunk.function.arguments

                    # 3. 当LLM指示工具调用完成时 (或者流自然结束)
                    if finish_reason == "tool_calls":
                        if len(tool_calls) == 0:
                            logger.warning(
                                "finish_reason 是 'tool_calls' 但没有收集到工具调用数据。"
                            )
                            # 这种情况不应该发生，但以防万一
                            break

                        if not run_tool_func:
                            yield "\n[错误: LLM请求工具调用，但未提供 'run_tool_func' 来执行它们。]\n"
                            logger.error("LLM请求工具调用，但 'run_tool_func' 未提供。")
                            return  # 结束生成

                        # 3.1 构建助手消息历史（包含工具调用请求）
                        # streamed_content = "".join(current_assistant_content_parts)
                        # current_assistant_content_parts.clear() # 清空，为下一轮准备 (如果递归)

                        logger.info(f"llm finsih with tool_calls, {tool_calls}")

                        assistant_tool_calls_list: List[
                            ChatCompletionMessageToolCall
                        ] = []
                        tools_to_execute_details = []  # 用于实际执行

                        for tool_call in tool_calls:
                            tc_id = tool_call["id"]
                            function_name = tool_call["function"]["name"]
                            args_json = tool_call["function"]["arguments"]
                            function_args = json.loads(args_json)
                            logger.info(
                                f"parse toolcall, {tc_id}, {function_name}, {args_json}, {function_args}"
                            )
                            if (
                                function_name and tc_id
                            ):  # 参数可能是空字符串，但名称和ID必须有
                                assistant_tool_calls_list.append(
                                    ChatCompletionMessageToolCall(
                                        id=tc_id,
                                        type="function",  # OpenAI 目前只支持 function 类型
                                        function={
                                            "name": function_name,
                                            "arguments": args_json,
                                        },
                                    )
                                )
                                tools_to_execute_details.append(
                                    {
                                        "id": tc_id,
                                        "name": function_name,
                                        "arguments": function_args,
                                    }
                                )
                            else:
                                logger.warning(
                                    f"收集到的工具调用数据不完整，ID {tc_id}: {tool_call}"
                                )

                        if not assistant_tool_calls_list:
                            logger.error(
                                "finish_reason='tool_calls' 但没有有效的工具调用可执行。"
                            )
                            yield "\n[错误: LLM请求工具调用，但未能解析出有效的工具信息。]\n"
                            return
                        logger.info(
                            f"add new Tool Call to Current Messages, tool_calls={assistant_tool_calls_list}"
                        )
                        current_messages.append(
                            {
                                "role": "assistant",
                                "content": None,  # 文本内容已经通过 yield 流式输出了
                                "tool_calls": [
                                    # SDK v1.x ChatCompletionMessageToolCall is not directly JSON serializable for message history
                                    # We need to convert them to dicts if we were to manually build this
                                    # However, the openai library handles this internally if we pass the objects.
                                    # For clarity and if current_messages is used outside this specific SDK context,
                                    # converting to dict structure matching API spec is safer.
                                    {
                                        "id": tc.id,
                                        "type": tc.type,
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments,
                                        },
                                    }
                                    for tc in assistant_tool_calls_list
                                ],
                            }
                        )
                        if ctx_manager:
                            for tc in assistant_tool_calls_list:
                                await ctx_manager.emit_and_append_to_history(
                                    ToolCall(
                                        tool_call_id=tc.id,
                                        tool_name=tc.function.name,
                                        tool_input=tc.function.arguments,
                                    )
                                )

                        # 3.2 执行工具
                        tool_results_messages: List[Dict[str, Any]] = []
                        # 可以考虑使用 asyncio.gather 并行执行独立的工具
                        for tool_data in tools_to_execute_details:
                            tool_name = tool_data["name"]
                            tool_args = tool_data["arguments"]
                            tool_call_id = tool_data["id"]

                            logger.info(
                                f"开始调用工具: {tool_name}, 参数: {tool_args}, ID: {tool_call_id}"
                            )
                            try:
                                # 调用 run_tool_func，它可能返回协程或异步生成器
                                tool_output = run_tool_func(tool_name, **tool_args)

                                tool_result_content = ""
                                if isinstance(tool_output, AsyncGenerator):
                                    # 如果是异步生成器，累积其所有输出
                                    accumulated_parts = []
                                    async for part in tool_output:
                                        accumulated_parts.append(str(part))
                                    tool_result_content = "".join(accumulated_parts)
                                    if (
                                        not tool_result_content
                                        and not accumulated_parts
                                    ):  # 区分空字符串和无任何 yield
                                        tool_result_content = (
                                            "[工具执行了，但没有产生任何内容]"
                                        )
                                elif asyncio.iscoroutine(tool_output):
                                    # 如果是协程，直接 await
                                    tool_result_content = await tool_output
                                else:
                                    # 如果是同步函数返回的直接结果 (尽管 run_tool_func 期望是 async)
                                    # 或者其他不期望的类型，先尝试转字符串
                                    logger.warning(
                                        f"工具 {tool_name} 返回了非预期类型: {type(tool_output)}。尝试转为字符串。"
                                    )
                                    tool_result_content = str(tool_output)

                                logger.info(
                                    f"工具 {tool_name} (ID: {tool_call_id}) 调用结果: {tool_result_content}"
                                )
                                tool_results_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "content": str(
                                            tool_result_content
                                        ),  # 结果必须是字符串
                                    }
                                )
                            except Exception as e:
                                logger.error(
                                    f"工具 {tool_name} (ID: {tool_call_id}) 执行失败: {e}",
                                    exc_info=True,
                                )
                                tool_results_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "content": f"执行工具 {tool_name} 时出错: {str(e)}",
                                    }
                                )

                        current_messages.extend(tool_results_messages)
                        if ctx_manager:
                            for tool_result in tool_results_messages:
                                await ctx_manager.emit_and_append_to_history(
                                    ToolResult(
                                        tool_call_id=tool_result["tool_call_id"],
                                        tool_name=tool_result["name"],
                                        tool_output=tool_result["content"],
                                    )
                                )

                        # 3.3 带着工具结果递归调用，继续获取LLM响应
                        # 清空 active_tool_calls_data 为下一轮 LLM 响应做准备 (虽然在递归调用中会是新的实例)
                        active_tool_calls_data.clear()

                        async for content_piece in self.invoke_stream(
                            system_prompt=system_prompt,  # 这些在递归中主要用于_prepare_params的默认参数
                            user_input=user_input,  # 实际历史由 messages 控制
                            messages=current_messages,  # 传递更新后的完整消息历史
                            run_tool_func=run_tool_func,  # 传递工具执行函数
                            **kwargs,  # 传递其他参数如 tools, tool_choice
                        ):
                            yield content_piece
                        return  # 结束本轮 invoke_stream，因为递归调用已处理后续

                # 4. 如果流正常结束 (finish_reason='stop', 'length', etc.) 且没有未处理的工具调用
                if active_tool_calls_data and finish_reason != "tool_calls":
                    # 这通常不应该发生，如果LLM打算调用工具，finish_reason应该是tool_calls
                    logger.warning(
                        f"流结束 (finish_reason: {finish_reason})，但仍有未处理的工具调用数据: {active_tool_calls_data}"
                    )
                    yield f"\n[警告: 流意外结束，可能存在未完成的工具调用请求: {list(active_tool_calls_data.keys())}]\n"

                break  # 成功完成或正常结束，退出重试循环

            except openai.RateLimitError as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"API速率限制。将在 {wait_time}s 后重试。尝试 {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"API速率限制，已达最大重试次数: {e}")
                    yield "\n错误: API速率限制超出，请稍后再试。\n"
                    break
            except openai.AuthenticationError as e:
                logger.error(f"OpenAI API认证失败: {e}", exc_info=True)
                yield "\n错误: API认证失败，请检查API密钥配置。\n"
                break
            except (openai.APIConnectionError, asyncio.TimeoutError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"连接错误: {e}. 将在 {wait_time}s 后重试。尝试 {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"连接OpenAI API失败，已达最大重试次数: {e}")
                    yield f"\n错误: 连接OpenAI API失败: {e}\n"
                    break
            except asyncio.CancelledError:
                logger.info("OpenAI API请求被取消")
                break  # 不再重试
            except Exception as e:
                logger.error(f"OpenAI API调用发生未预期错误: {e}", exc_info=True)
                yield f"\n错误: {str(e)}\n"
                break  # 不再重试未知错误

    def _prepare_params(
        self,
        system_prompt: str,
        prompt: str,
        current_messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        准备 API 调用参数

        Args:
            system_prompt: 系统提示 (用于 current_messages 为 None 时)
            prompt: 用户提示 (用于 current_messages 为 None 时)
            current_messages: 当前的对话消息列表
            **kwargs: 运行时参数，会覆盖实例的默认设置

        Returns:
            API 调用参数字典
        """
        # 优先使用 current_messages (如果提供)
        if current_messages:
            messages_payload = current_messages
        else:
            messages_payload = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

        # 基本参数，允许被 kwargs 覆盖
        params: Dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": messages_payload,
        }

        # 可选参数
        max_tokens_to_use = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens_to_use is not None:
            params["max_tokens"] = max_tokens_to_use

        # 工具相关参数 (来自 kwargs)
        if "tools" in kwargs:
            params["tools"] = kwargs["tools"]
        if (
            "tool_choice" in kwargs
        ):  # e.g., "auto", "none", {"type": "function", "function": {"name": "my_function"}}
            params["tool_choice"] = kwargs["tool_choice"]

        # 合并 self.extra_params (kwargs 中未指定的参数)
        for key, value in self.extra_params.items():
            if key not in params:  # 避免覆盖已经从 kwargs 或方法固定设置的参数
                params[key] = value

        # 确保 kwargs 中其他未明确处理的参数也被添加，这允许完全的灵活性
        # 但要小心不要覆盖核心参数如 'model', 'messages', 'stream' 等已被设置的
        # 这个逻辑可以更精细，但通常 self.extra_params 和显式 kwargs 已经覆盖多数情况
        # for key, value in kwargs.items():
        #     if key not in params and key not in ["system_prompt", "prompt", "current_messages", "client_args"]:
        #         params[key] = value
        # 上面的逻辑可能过于宽泛，如果kwargs包含内部使用的如system_prompt，不应直接加入params
        # 通常 tools, tool_choice, response_format 等应该在kwargs中明确传递给completions.create
        # self.extra_params 可以用来存放一些不常变动的API参数。

        return params