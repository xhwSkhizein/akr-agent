#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Agent core class
"""

import logging
from typing import AsyncGenerator

from .agent_config_engine import AgentConfigEngine

from .rule_config import AgentConfig
from .utils import get_workspace_root, get_container_workspace
from .context_manager import ContextManager
from .workspace_manager import WorkspaceManager
from .dispatcher import DynamicDispatcher
from .output_stream_manager import OutputChunk



class Agent:
    """Agent core class"""

    def __init__(self, config_dir: str, sid: str):
        """
        Initialize Agent

        Args:
            config_dir: Base path of prompt configuration files
            sid: Session ID
        """
        # FIXME: logger use sid
        self._logger = logging.getLogger(__name__)
        
        if not config_dir or not config_dir.strip():
            raise ValueError("config_dir must be provided")

        self._logger.info(f"Agent init with config_dir: {config_dir}, sid: {sid}")
        self._config: AgentConfig = AgentConfigEngine.load(config_dir)
        self._workspace_manager = WorkspaceManager(
            root=get_workspace_root(sid),
            container_workspace=get_container_workspace(sid),
        )
        self._context_manager = ContextManager(logger=self._logger)
        
        self._context_manager.set_system_prompt(self._config.system_prompt)
        self._dispatcher = DynamicDispatcher(
            initial_rules=self._config.rules,
            workspace_manager=self._workspace_manager,
            context_manager=self._context_manager,
            max_concurrent_tasks=self._config.max_concurrent_tasks,
            timeout_detection_time=self._config.timeout_detection_time,
            stream_registration_timeout=self._config.stream_registration_timeout,
            logger=self._logger,
        )

    async def run_dynamic(self, user_input: str) -> AsyncGenerator[OutputChunk, None]:
        """
        Run Agent's dynamic conversation flow

        Args:
            user_input: User input

        Yields:
            str: Generated response chunk
        """
        self._logger.info(f"Agent run_dynamic started with input: {user_input}")

        await self._dispatcher.add_user_input(user_input)

        async for chunk in self._dispatcher.get_output_stream():
            yield chunk

        self._logger.info("Agent run_dynamic finished.")
        # TODO: Consider a shutdown for the dispatcher if the agent instance is not reused
        # await self._dispatcher.shutdown()
