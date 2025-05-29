#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
DeepSea Agent 库示例
"""

import asyncio
import json
import logging
import os

from core.agent import Agent
from core.tools.base import ToolCenter
from core.tools.tool_llm import LLMCallTool
from core.tools.tool_search import DuckDuckGoSearchTool, TavilySearchTool


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

## 注册工具
ToolCenter.register(
    tool=LLMCallTool(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=1000,
        stream=True,
    )
)
# llm_call_tool_def = ToolCenter.get_definition("LLMCallTool")
# logger.info(json.dumps(llm_call_tool_def, indent=2, ensure_ascii=False))
ToolCenter.register(tool=DuckDuckGoSearchTool(), name="DuckDuckGoSearchTool")
search_ddg_tool_def = ToolCenter.get_definition("DuckDuckGoSearchTool")
logger.info(json.dumps(search_ddg_tool_def, indent=2, ensure_ascii=False))
# ToolCenter.register(tool=TavilySearchTool(), name="TavilySearchTool")
# tavily_search_def = ToolCenter.get_definition("TavilySearchTool")
# logger.info(json.dumps(tavily_search_def, indent=2, ensure_ascii=False))

# 主函数
async def main():
    """主函数。"""

    # global_ctx = GlobalContext()

    # 创建 Agent 实例
    agent = Agent(config_dir="prompts/CoachLi/v1", sid="test")

    user_input_2 = "1+1=？"
    logger.info(f"\n--- 用户输入 ---\n{user_input_2}")

    async for chunk in agent.run_dynamic(user_input_2):
        # 将ResponseChunk对象转换为字典再序列化为JSON
        print(chunk.content, end="", flush=True)

    logger.info("\n--- 所有上下文 ---\n")
    logger.info(
        json.dumps(agent._context_manager.get_context().to_dict(), indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
