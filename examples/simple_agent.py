#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AKR-Agent 简单示例
"""

import asyncio
import json
import logging
import os
import sys

# 添加项目根目录到 Python 路径，方便开发时导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akr_agent import Agent, ToolCenter
from akr_agent.tools.tool_llm import LLMCallTool
from akr_agent.tools.tool_search import DuckDuckGoSearchTool


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    """主函数"""
    # 注册工具
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
    
    # 创建 Agent 实例
    agent = Agent(config_dir="examples/prompts/CoachLi/v1", sid="test")
    
    # 用户输入
    user_input = "我想开始健身，有什么建议？"
    print(f"\n--- 用户输入 ---\n{user_input}")
    
    # 运行 Agent 并获取响应
    print("\n--- Agent 响应 ---")
    async for chunk in agent.run_dynamic(user_input):
        print(chunk.content, end="", flush=True)
    
    print("\n\n--- 完成 ---\n")
    print("\n--- 所有上下文 ---\n")
    print(
        json.dumps(agent._context_manager.get_context().to_dict(), indent=2, ensure_ascii=False)
    )


if __name__ == "__main__":
    asyncio.run(main())
