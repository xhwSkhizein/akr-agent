#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AKR-Agent Simple Example
"""

import asyncio
import json
import logging
import os
import sys

# Add project root directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akr_agent import Agent, ToolCenter
from akr_agent.tools.tool_llm import LLMCallTool
from akr_agent.tools.tool_search import DuckDuckGoSearchTool


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    """Main function"""
    # Register tools
    ToolCenter.register(
        tool=LLMCallTool(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model="gpt-4o-mini",
            temperature=0.7,
            max_tokens=1000,
            stream=True,
        )
    )
    ToolCenter.register(tool=DuckDuckGoSearchTool(), name="DuckDuckGoSearchTool")
    
    # Create Agent instance
    agent = Agent(config_dir="examples/prompts/CoachLi/v1", sid="test")
    
    # User input
    user_input = "I want to start fitness, what are the suggestions?"
    print(f"\n--- User Input ---\n{user_input}")
    
    # Run Agent and get response
    print("\n--- Agent Response ---")
    async for chunk in agent.run_dynamic(user_input):
        print(chunk.content, end="", flush=True)
    
    print("\n\n--- Done ---\n")
    print("\n--- All Context ---\n")
    print(
        json.dumps(agent._context_manager.get_context().to_dict(), indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
