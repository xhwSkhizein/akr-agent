"""
OpenAI LLM client implementation
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
from .llm_base import ToolCall, ToolResult, TokenUsage


logger = logging.getLogger(__name__)


class OpenAIClient(LLMClient):
    """
    OpenAI API client implementation (support tool_calls)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",  # suggest use new model support tool_calls
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        """
        Initialize OpenAI client

        Args:
            api_key: OpenAI API key, if None then use environment variable
            model: Model name
            temperature: Temperature parameter
            max_tokens: Maximum tokens
            **kwargs: Other OpenAI API parameters (e.g. base_url, timeout, etc.)
        """
        self.client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, **kwargs.pop("client_args", {})
        )  # pass additional parameters to client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_params = kwargs  # other parameters passed to completions.create
        logging.info(f"Initialize OpenAI client, model: {model}")

    async def invoke_stream(
        self,
        system_prompt: str,
        user_input: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        run_tool_func: Optional[Callable[[str, str], Any]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Streamly invoke OpenAI API and return response stream, support tool_calls.

        Args:
            system_prompt: System prompt (only used to build initial messages on first call or when messages is None)
            user_input: User input (only used to build initial messages on first call or when messages is None)
            messages: Optional, preset messages list. If provided, system_prompt and user_input are ignored to build initial messages.
            run_tool_func: Optional async function to execute tool calls. Signature should be: async def run_tool(tool_name: str, tool_args: str) -> Any
            **kwargs: Override default parameters or pass additional parameters (e.g. tools, tool_choice)
                - ctx_manager: Context manager, used to output assistant messages

        Yields:
            Response fragment (str)
        """
        current_messages: List[Dict[str, Any]]
        if messages is not None:
            current_messages = list(messages)  # use provided message list copy
        else:
            current_messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]

        # prepare API call parameters
        # note: kwargs passed to _prepare_params, it will merge instance attributes and these runtime parameters
        api_params = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        api_params.update(self._prepare_params(
            system_prompt=system_prompt,  # pass to _prepare_params for possible initial message building logic
            prompt=user_input,  # same as above
            current_messages=current_messages,  # most important: pass current message history
            **kwargs,  # include tools, tool_choice, etc
        ))
        api_params["stream"] = True
        api_params["stream_options"] = {
            "include_usage": True,
        }
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
                logging.debug(f"OPENAI invoke stream params: {api_params}")
                response_stream: AsyncGenerator[ChatCompletionChunk, None] = (
                    await self.client.chat.completions.create(**api_params)
                )

                # used to accumulate tool_calls data in current LLM response
                # key: tool_call_id, value: {"id": ..., "type": "function", "function_name": ..., "function_arguments": ...}
                active_tool_calls_data: Dict[str, Dict[str, str]] = {}
                tool_calls = []
                # used to accumulate text content in current LLM response (if LLM speaks before requesting tool calls)
                # current_assistant_content_parts: List[str] = []

                async for chunk in response_stream:
                    if chunk.usage:
                        # token usage statistics
                        total_tokens = chunk.usage.total_tokens
                        prompt_tokens = chunk.usage.prompt_tokens
                        completion_tokens = chunk.usage.completion_tokens
                        completion_tokens_details = (
                            chunk.usage.completion_tokens_details
                        )
                        prompt_tokens_details = chunk.usage.prompt_tokens_details
                        if ctx_manager is not None:
                            await ctx_manager.emit_and_append_to_history(
                                TokenUsage(
                                    role="assistant",
                                    model=self.model,
                                    total_tokens=total_tokens,
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    completion_tokens_details=(
                                        completion_tokens_details.to_dict()
                                        if completion_tokens_details
                                        else None
                                    ),
                                    prompt_tokens_details=(
                                        prompt_tokens_details.to_dict()
                                        if prompt_tokens_details
                                        else None
                                    ),
                                )
                            )
                        logger.info(
                            f"Llm Call Token cost: {chunk.usage.model_dump_json()}"
                        )

                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason

                    # 1. process text content
                    if delta and delta.content:
                        # current_assistant_content_parts.append(delta.content)
                        yield delta.content

                    # 2. process tool_calls
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

                    # 3. when LLM indicates tool calls are finished (or stream naturally ends)
                    if finish_reason == "tool_calls":
                        if len(tool_calls) == 0:
                            logger.warning(
                                "finish_reason is 'tool_calls' but no tool call data collected."
                            )
                            # This should not happen, but just in case
                            break

                        if not run_tool_func:
                            yield "\n[Error: LLM requests tool calls, but 'run_tool_func' is not provided to execute them.]\n"
                            logger.error(
                                "LLM requests tool calls, but 'run_tool_func' is not provided."
                            )
                            return  # end generation

                        # 3.1 build assistant message history (include tool call requests)
                        # streamed_content = "".join(current_assistant_content_parts)
                        # current_assistant_content_parts.clear() # clear for next round (if recursive)

                        logger.info(f"llm finsih with tool_calls, {tool_calls}")

                        assistant_tool_calls_list: List[
                            ChatCompletionMessageToolCall
                        ] = []
                        tools_to_execute_details = []  # used to execute tools

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
                            ):  # Parameters may be empty strings, but name and ID must be present
                                assistant_tool_calls_list.append(
                                    ChatCompletionMessageToolCall(
                                        id=tc_id,
                                        type="function",  # OpenAI currently only supports function type
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
                                    f"collect tool call data incomplete, ID {tc_id}: {tool_call}"
                                )

                        if not assistant_tool_calls_list:
                            logger.error(
                                "finish_reason='tool_calls' but no valid tool calls to execute."
                            )
                            yield "\n[error: LLM requests tool calls, but unable to parse valid tool information.]\n"
                            return
                        logger.info(
                            f"add new Tool Call to Current Messages, tool_calls={assistant_tool_calls_list}"
                        )
                        current_messages.append(
                            {
                                "role": "assistant",
                                "content": None,  # Text content has already been yielded
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

                        # 3.2 execute tools
                        tool_results_messages: List[Dict[str, Any]] = []
                        # can consider using asyncio.gather to parallel execute independent tools
                        for tool_data in tools_to_execute_details:
                            tool_name = tool_data["name"]
                            tool_args = tool_data["arguments"]
                            tool_call_id = tool_data["id"]

                            logger.info(
                                f"invoke tool: {tool_name}, args: {tool_args}, id: {tool_call_id}"
                            )
                            try:
                                # call run_tool_func, it may return coroutine or async generator
                                tool_output = run_tool_func(tool_name, **tool_args)

                                tool_result_content = ""
                                if isinstance(tool_output, AsyncGenerator):
                                    # if it's async generator, accumulate all outputs
                                    accumulated_parts = []
                                    async for part in tool_output:
                                        accumulated_parts.append(str(part))
                                    tool_result_content = "".join(accumulated_parts)
                                    if (
                                        not tool_result_content
                                        and not accumulated_parts
                                    ):  # distinguish empty string and no yield at all
                                        tool_result_content = (
                                            "[tool executed, but no content generated]"
                                        )
                                elif asyncio.iscoroutine(tool_output):
                                    # if it's coroutine, await directly
                                    tool_result_content = await tool_output
                                else:
                                    # if it's sync function return value (despite run_tool_func expects async)
                                    # or other unexpected type, try to convert to string
                                    logger.warning(
                                        f"tool {tool_name} returned unexpected type: {type(tool_output)}. Trying to convert to string."
                                    )
                                    tool_result_content = str(tool_output)

                                logger.info(
                                    f"tool {tool_name} (ID: {tool_call_id}) result: {tool_result_content}"
                                )
                                tool_results_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "content": str(
                                            tool_result_content
                                        ),  # result must be string
                                    }
                                )
                            except Exception as e:
                                logger.error(
                                    f"tool {tool_name} (ID: {tool_call_id}) execution failed: {e}",
                                    exc_info=True,
                                )
                                tool_results_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "name": tool_name,
                                        "content": f"error: failed to execute tool {tool_name}: {str(e)}",
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

                        # 3.3 Recursive call, continue getting LLM response
                        # Clear active_tool_calls_data for next LLM response (although a new instance will be created in recursive call)
                        active_tool_calls_data.clear()

                        async for content_piece in self.invoke_stream(
                            system_prompt=system_prompt,  # These are used for _prepare_params default parameters in recursive call
                            user_input=user_input,  # Actual history is controlled by messages
                            messages=current_messages,  # Pass updated complete message history
                            run_tool_func=run_tool_func,  # Pass tool execution function
                            **kwargs,  # Pass other parameters like tools, tool_choice
                        ):
                            yield content_piece
                        return  # End this round of invoke_stream, because recursive call has handled the rest

                # 4. If the stream ends normally (finish_reason='stop', 'length', etc.) and there are no unprocessed tool calls
                if active_tool_calls_data and finish_reason != "tool_calls":
                    # This should not happen, if LLM plans to call tools, finish_reason should be tool_calls
                    logger.warning(
                        f"Stream ended (finish_reason: {finish_reason}), but there are still unprocessed tool call data: {active_tool_calls_data}"
                    )
                    yield f"\n[warning: stream ended unexpectedly, there may be incomplete tool call requests: {list(active_tool_calls_data.keys())}]\n"

                break  # Successfully completed or normally ended, exit retry loop

            except openai.RateLimitError as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"API rate limit exceeded. Will retry in {wait_time}s. Attempt {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"API rate limit exceeded, reached maximum retry count: {e}"
                    )
                    yield "\nError: API rate limit exceeded, please try again later.\n"
                    break
            except openai.AuthenticationError as e:
                logger.error(f"OpenAI API authentication failed: {e}", exc_info=True)
                yield "\nError: API authentication failed, please check API key configuration.\n"
                break
            except (openai.APIConnectionError, asyncio.TimeoutError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = backoff_factor**retry_count
                    logger.warning(
                        f"Connection error: {e}. Will retry in {wait_time}s. Attempt {retry_count}/{max_retries}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to connect to OpenAI API, reached maximum retry count: {e}"
                    )
                    yield f"\nError: Failed to connect to OpenAI API: {e}\n"
                    break
            except asyncio.CancelledError:
                logger.info("OpenAI API request cancelled")
                break  # Do not retry
            except Exception as e:
                logger.error(f"Unexpected error in OpenAI API call: {e}", exc_info=True)
                yield f"\nError: {str(e)}\n"
                break  # Do not retry unknown error

    def _prepare_params(
        self,
        system_prompt: str,
        prompt: str,
        current_messages: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Prepare API call parameters

        Args:
            system_prompt: System prompt (used when current_messages is None)
            prompt: User prompt (used when current_messages is None)
            current_messages: Current conversation message list
            **kwargs: Runtime parameters, will override instance default settings

        Returns:
            API call parameters dictionary
        """
        # Use current_messages if provided
        if current_messages:
            messages_payload = current_messages
        else:
            messages_payload = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

        # Basic parameters, allow being overridden by kwargs
        params: Dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": messages_payload,
        }

        # Optional parameters
        max_tokens_to_use = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens_to_use is not None:
            params["max_tokens"] = max_tokens_to_use

        # Tool related parameters (from kwargs)
        if "tools" in kwargs:
            params["tools"] = kwargs["tools"]
        if (
            "tool_choice" in kwargs
        ):  # e.g., "auto", "none", {"type": "function", "function": {"name": "my_function"}}
            params["tool_choice"] = kwargs["tool_choice"]

        # Merge self.extra_params (parameters not specified in kwargs)
        for key, value in self.extra_params.items():
            if (
                key not in params
            ):  # Avoid overriding parameters already set in kwargs or method fixed settings
                params[key] = value

        # Ensure other parameters not explicitly handled in kwargs are also added, allowing complete flexibility
        # But be careful not to override core parameters like 'model', 'messages', 'stream' that have already been set
        # This logic can be refined, but usually self.extra_params and explicit kwargs already cover most cases
        # for key, value in kwargs.items():
        #     if key not in params and key not in ["system_prompt", "prompt", "current_messages", "client_args"]:
        #         params[key] = value
        # The above logic may be too broad, if kwargs contains internal used like system_prompt, should not directly add to params
        # Usually tools, tool_choice, response_format etc. should be explicitly passed to completions.create
        # self.extra_params can be used to store some API parameters that do not change often.

        return params
