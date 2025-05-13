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
from config.agent_config import LLMConfig


# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# OpenAI LLM 配置
def get_openai_config() -> LLMConfig:
    """获取 OpenAI LLM 配置。"""
    return LLMConfig(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=1000,
        stream=True,
    )


# 主函数
async def main():
    """主函数。"""
    # 获取 LLM 配置
    llm_config = get_openai_config()

    # 创建 Agent 实例，使用配置文件路径
    agent = Agent(
        config_dir="prompts/CoachLi/v1",
        llm_cfg=llm_config
    )

    user_input_2 = "我刚刚摔断了腿，应该怎么进行康复训练？"
    print(f"\n--- 用户输入 ---\n{user_input_2}")

    async for chunk in agent.run_dynamic(user_input_2):
        print(chunk, end="", flush=True)

    print("\n--- 所有上下文 ---\n")
    print(json.dumps(agent._observable_ctx.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
