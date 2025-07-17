#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AKR-Agent Simple Example
"""

import asyncio
import json
import os
import sys

# Add project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akr_agent.agent import Agent
from akr_agent.tools.base import ToolCenter
from akr_agent.tools.tool_llm import LLMCallTool
from akr_agent.tools.tool_search import DuckDuckGoSearchTool


from loguru import logger
import sys

# 设置日志级别为DEBUG
logger.remove()
logger.add(sys.stderr, level="DEBUG")

async def main():
    """Main function"""
    # Register tools
    ToolCenter.register(
        tool=LLMCallTool(
            api_key=os.environ.get("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-turbo-latest",
            temperature=0.7,
            max_tokens=1000,
            stream=True,
            enable_logging=True,
            log_dir="logs/llm_calls"
        )
    )
    ToolCenter.register(tool=DuckDuckGoSearchTool(), name="DuckDuckGoSearchTool")
    
    # Create Agent instance
    agent = Agent(config_dir="examples/prompts/CoachLi/v1", sid="test")
    
    # User input
    user_input = "具体描述食物组成、克重预估"
    image_url = "https://i.ibb.co/NMhXwPD/72d59001-b6a7-473c-9b76-32ea9f959363.png"
    logger.info(f"\n--- User Input ---\n{user_input}")
    
    # Run Agent and get response
    logger.info("\n--- Agent Response ---")
    async for chunk in agent.run_dynamic(user_input, image_url=image_url, image_url_detail="high"):
        logger.info(chunk.content)
    
    logger.info("\n\n--- Done ---\n")
    logger.info("\n--- All Context ---\n")
    logger.info(
        json.dumps(agent._context_manager.get_context().to_dict(), indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
