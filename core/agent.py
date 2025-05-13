#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Agent 核心类
"""

import logging
from typing import AsyncGenerator, Optional
from config.agent_config import LLMConfig
from config.prompt_engine import AgentConfigEngine
from core.dispatcher import RuleDispatcher
from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from llm import OpenAIClient

logger = logging.getLogger(__name__)


class Agent:
    """Agent 核心类"""

    def __init__(self, config_dir: str, llm_cfg: Optional[LLMConfig] = None):
        """
        初始化 Agent

        Args:
            config_dir: prompt 配置文件的基础路径
            llm_cfg: 全局 LLM 配置对象
        """
        if not config_dir or not config_dir.strip():
            raise ValueError("config_dir must be provided")

        self._config = AgentConfigEngine.load(config_dir)
        self._llm_config = llm_cfg
        self._event_bus = EventBus()
        self._observable_ctx = ObservableCtx(
            config=self._config, event_bus=self._event_bus
        )
        self._rule_dispatcher = RuleDispatcher(
            initial_rules=self._config.rules,
            event_bus=self._event_bus,
            ctx=self._observable_ctx,
            llm_client=OpenAIClient(
                model=self._llm_config.model, api_key=self._llm_config.api_key
            ),
            agent_system_prompt=self._config.system_prompt,
        )

    async def run_dynamic(self, user_input: str) -> AsyncGenerator[str, None]:
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
        await self._rule_dispatcher.dispatch_initial()

        async for chunk in self._rule_dispatcher.get_output_stream():
            yield chunk

        logger.debug("Agent run_dynamic finished.")
        # TODO: Consider a shutdown for the dispatcher if the agent instance is not reused
        # await self._rule_dispatcher.shutdown()
