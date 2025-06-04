# AKR-Agent: Agent Know Rules

[![PyPI version](https://badge.fury.io/py/akr-agent.svg)](https://badge.fury.io/py/akr-agent)
[![Python Version](https://img.shields.io/pypi/pyversions/akr-agent.svg)](https://pypi.org/project/akr-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AKR-Agent 是一个灵活的基于规则的 AI Agent 框架，旨在帮助开发者快速构建和部署智能代理。该框架支持动态规则配置、工具注册和上下文管理，使开发者能够轻松创建各种类型的智能代理应用。

## 安装

```bash
pip install akr-agent
```

## 快速开始

```python
import asyncio
import os
from akr_agent import Agent, ToolCenter
from akr_agent.tools.tool_llm import LLMCallTool

# 注册 LLM 工具
ToolCenter.register(
    tool=LLMCallTool(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model="gpt-4o-mini",
        temperature=0.7,
        max_tokens=1000,
        stream=True,
    )
)

async def main():
    # 创建 Agent 实例，指定配置目录
    agent = Agent(config_dir="prompts/CoachLi/v1")
    
    # 用户输入
    user_input = "我想开始健身，有什么建议？"
    print(f"\n--- 用户输入 ---\n{user_input}")
    
    # 运行 Agent 并获取响应
    print("\n--- Agent 响应 ---")
    async for chunk in agent.run_dynamic(user_input):
        print(chunk.content, end="", flush=True)
    
    print("\n\n--- 完成 ---")

if __name__ == "__main__":
    asyncio.run(main())
```

## 架构设计

* 优势：项目采用了清晰的模块化设计，核心组件分工明确：
    * Agent 作为核心类管理整体流程
    * DynamicDispatcher 负责规则调度和执行
    * ObservableContext 提供响应式上下文管理
    * EventBus 实现事件驱动机制
    * ToolCenter 提供工具注册和调用能力


## 核心功能

1. **规则引擎**：基于配置的规则系统设计灵活，支持条件匹配和动态规则生成
2. **上下文管理**：实现了可观察的上下文机制，支持数据变更通知
3. **工具系统**：提供了工具注册和调用的统一接口，支持异步流式输出
4. **LLM集成**：封装了OpenAI API，支持流式响应和工具调用

## 配置系统

* 采用YAML配置文件管理Agent行为，包括系统提示、规则定义等
* 支持Jinja2模板渲染，可根据上下文动态生成提示

### 配置目录结构

```
prompts/
└── YourAgent/version_x/
    ├── meta.yaml           # Agent元数据
    ├── system_prompt.yaml  # 系统提示
    └── rules/              # 规则目录
        ├── rule1.yaml      # 规则1
        ├── rule2.yaml      # 规则2
        └── ...             # 至少要确保有一条规则可以处理用户输入
```

### meta.yaml 示例

```yaml
agent:
  name: "Your Agent Name"
  version: "v1"

meta:
  name: "Agent Display Name"
  desc: "Description of your agent"
  parameters:
    skill: 
      - "Skill 1"
      - "Skill 2"
    advantages:
      - "Advantage 1"
    disadvantages:
      - "Disadvantage 1"
```

### system_prompt.yaml 示例

```yaml
content: |
  你是{{ meta.name }}, 你是一个 {{ meta.desc }}。
  你非常乐于帮助用户进行 {{ meta.parameters.skill | join(', ') }}。
  你更擅长帮助用户进行 {{ meta.parameters.advantages | join(', ') }}，
  但是不擅长帮助用户进行 {{ meta.parameters.disadvantages | join(', ') }}。
```

### 规则配置示例

```yaml
name: "basic_reply"
depend_ctx_key:
  - "user_input"
match_condition: "True"  # 始终匹配
prompt: |
  请根据用户的问题提供有用的回答。
prompt_detail: |
  用户的问题是：{{ user_input }}
tool: "LLMCallTool" # 在前面注册的工具名称
tool_params:
  ctx: ["user_input"]
  config: ["prompt", "prompt_detail"]
  extra:
    - tools:
      - "ToolNameThatLLMCanUse"
tool_result_target: "DIRECT_RETURN" # 直接返回给用户
```



## 自定义工具

您可以通过继承 `Tool` 基类来创建自定义工具：

```python
from typing import AsyncGenerator
from akr_agent import Tool, ToolCenter

class WeatherTool(Tool):
    """获取天气信息的工具"""
    
    name = "WeatherTool"
    description = "获取指定城市的天气信息"
    
    def __init__(self, api_key=None):
        self.api_key = api_key
    
    async def run(self, city: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        获取城市天气
        
        Args:
            city: 城市名称
        """
        # 这里实现天气API调用逻辑
        weather_info = f"{city}的天气：晴天，温度25°C"
        yield weather_info

# 注册工具
ToolCenter.register(tool=WeatherTool(api_key="your_weather_api_key"))
```

## 开发指南

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 运行测试

```bash
python -m pytest tests
```

### 代码风格

我们使用 Black 和 isort 来保持代码风格一致：

```bash
black akr_agent
isort akr_agent
```

### 类型检查

使用 mypy 进行类型检查：

```bash
mypy akr_agent
```

## 贡献指南

我们欢迎所有形式的贡献，包括但不限于：

1. 报告问题和建议改进
2. 提交代码修复或新功能
3. 改进文档
4. 添加测试用例

### 贡献流程

1. Fork 项目仓库
2. 创建您的特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交您的更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建一个 Pull Request

## 路线图

- [ ] 支持更多 LLM 提供商
- [ ] 添加更多内置工具
- [ ] 改进错误处理和恢复机制
- [ ] 添加更多示例和文档
- [ ] 实现缓存机制和性能优化

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件