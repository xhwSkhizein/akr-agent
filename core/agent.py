#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Agent 核心类
"""

import logging
from typing import AsyncGenerator
from core.prompt_engine import AgentConfigEngine
from core.dispatcher import RuleDispatcher
from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from core.chunk import ResponseChunk

logger = logging.getLogger(__name__)


class Agent:
    """Agent 核心类"""

    def __init__(self, config_dir: str):
        """
        初始化 Agent

        Args:
            config_dir: prompt 配置文件的基础路径
        """
        if not config_dir or not config_dir.strip():
            raise ValueError("config_dir must be provided")

        self._config = AgentConfigEngine.load(config_dir)
        self._event_bus = EventBus()
        self._observable_ctx = ObservableCtx(
            event_bus=self._event_bus, system_prompt=self._config.system_prompt
        )
        self._rule_dispatcher = RuleDispatcher(
            initial_rules=self._config.rules,
            event_bus=self._event_bus,
            ctx=self._observable_ctx,
        )

    async def run_dynamic(self, user_input: str) -> AsyncGenerator[ResponseChunk, None]:
        """
        运行 Agent 的动态对话流程

        Args:
            user_input: 用户输入

        Yields:
            str: 生成的回复片段
        """
        logger.debug(f"Agent run_dynamic started with input: {user_input}")

        await self._observable_ctx.set("user_input", user_input)
        await self._observable_ctx.append("dialogue.history", f"Q: {user_input}")

        async for chunk in self._rule_dispatcher.get_output_stream():
            yield chunk

        logger.debug("Agent run_dynamic finished.")
        # TODO: Consider a shutdown for the dispatcher if the agent instance is not reused
        # await self._rule_dispatcher.shutdown()
