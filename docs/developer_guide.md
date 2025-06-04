# DeepSea Agent 开发者指南

本指南旨在帮助开发者快速上手DeepSea Agent框架，包括环境设置、基本用法、自定义扩展和最佳实践。

## 目录

- [环境设置](#环境设置)
- [快速开始](#快速开始)
- [创建自定义Agent](#创建自定义agent)
- [自定义工具](#自定义工具)
- [规则配置详解](#规则配置详解)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

## 环境设置

### 依赖安装

首先，确保你已经安装了Python 3.8+，然后安装Akr-Agent的依赖：

```bash
pip install -r requirements.txt
```

### 环境变量配置

对于使用OpenAI API的功能，你需要设置API密钥：

```bash
export OPENAI_API_KEY=your_api_key_here
```

## 快速开始

以下是一个基本的示例，展示如何创建和运行一个简单的Agent：

```python
import asyncio
import os
from agent import Agent
from tools.base import ToolCenter
from tools.tool_llm import LLMCallTool

# 注册LLM工具
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
    # 创建Agent实例，指定配置目录
    agent = Agent(config_dir="prompts/CoachLi/v1")
    
    # 用户输入
    user_input = "我大腿骨折了，应该怎么进行康复训练？"
    print(f"\n--- 用户输入 ---\n{user_input}")
    
    # 运行Agent并获取响应
    async for chunk in agent.run_dynamic(user_input):
        print(chunk.content, end="", flush=True)
    
    print("\n--- 完成 ---\n")
    print("\n--- 所有上下文 ---\n")
    print(
        json.dumps(agent._context_manager.get_context().to_dict(), indent=2, ensure_ascii=False)
    )

if __name__ == "__main__":
    asyncio.run(main())
```

## 创建自定义Agent

### 配置目录结构

创建一个自定义Agent需要准备以下配置文件：

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

### meta.yaml

```yaml
meta:
  name: "Your Agent Name"
  desc: "Description of your agent"
  parameters:
    param1: value1
    param2: value2

agent:
  name: "YourAgent"
  version: "v1"
```

### system_prompt.yaml

```yaml
content: |
  你是一个名为 {{ meta.name }} 的AI助手。
  你的主要职责是：{{ meta.desc }}
  
  请遵循以下原则：
  1. 提供准确、有帮助的信息
  2. 保持友好和专业的态度
  3. 如果不确定，请坦诚表达
```

### 规则配置示例

创建一个基本的回复规则（rules/basic_reply.yaml）：

```yaml
name: "basic_reply"
depend_ctx_key: ["user_input"]
match_condition: "True"  # 始终匹配
prompt: |
  请根据用户的问题提供有用的回答。
prompt_detail: |
  用户的问题是：{{ user_input }}
tool: "LLMCallTool" # 在前面注册的工具名称
tool_params:
  ctx: ["user_input"]
  config: ["prompt", "prompt_detail"]
tool_result_target: "DIRECT_RETURN" # 直接返回给用户
```

## 自定义工具

### 创建自定义工具

你可以通过继承`Tool`基类来创建自定义工具：

```python
from typing import AsyncGenerator
from core.tools.base import Tool, ToolCenter

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

### 使用自定义工具的规则

创建一个使用天气工具的规则（rules/weather_query.yaml）：

```yaml
name: "weather_query"
depend_ctx_key: ["user_input"]
match_condition: "'天气' in ctx.get('user_input')"
prompt: |
  分析用户的输入，提取出用户想要查询天气的城市名称。
prompt_detail: |
  用户的输入是：{{ user_input }}
  
  请返回一个JSON格式的结果，包含城市名称：
  {"city": "城市名称"}
tool: "LLMCallTool"
tool_params:
  ctx: ["user_input"]
  config: ["prompt", "prompt_detail"]
  extra:
    tools:
      - WeatherTool # 指定 LLM 可以使用的工具名称
tool_result_target: "DIRECT_RETURN"
```


## 规则配置详解

### 规则配置字段说明

- **name**: 规则名称，用于标识规则
- **depend_ctx_key**: 规则依赖的上下文键，当这些键的值发生变化时，规则会被重新评估
- **match_condition**: 规则匹配条件，是一个Python表达式，会被eval执行
- **prompt**: 规则的主要提示
- **prompt_detail**: 规则的详细提示，用于补充主要提示
- **tool**: 要执行的工具名称
- **tool_params**: 工具参数配置
  - **ctx**: 从上下文中获取的参数
  - **config**: 从规则配置中获取的参数
  - **extra**: 额外的固定参数
    - **tools**: 指定 LLM 可以使用的工具名称列表
    - **model**: 指定 LLM 模型名称
    - **others**: 其他额外的参数
- **tool_result_target**: 工具执行结果的处理方式
  - **AS_CONTEXT**: 将结果存储到上下文中
  - **DIRECT_RETURN**: 直接返回给用户
  - **NEW_RULES**: 生成新的规则
- **tool_result_key**: 当tool_result_target为AS_CONTEXT时，用于存储结果的上下文键
- **auto_generated**: 是否是自动生成的规则
- **priority**: 优先级

### 规则执行流程

1. 当上下文中的某个键发生变化时，规则调度器会检查所有依赖该键的规则
2. 对于每个规则，评估其match_condition
3. 如果条件满足，则执行规则对应的工具
4. 根据tool_result_target处理工具执行结果

## 最佳实践

### 规则设计原则

1. **单一职责**: 每个规则应该只负责一个明确的任务
2. **明确依赖**: 清晰定义规则依赖的上下文键
3. **精确条件**: 编写精确的匹配条件，避免不必要的规则评估
4. **合理分层**: 将复杂任务拆分为多个规则，形成处理链

### 提示工程

1. **清晰指令**: 在prompt中提供清晰、具体的指令
2. **上下文利用**: 使用Jinja2模板语法引用上下文数据
3. **结构化输出**: 对于需要进一步处理的结果，要求LLM返回结构化的JSON

### 错误处理

1. **验证输入**: 在工具实现中验证输入参数
2. **优雅降级**: 当工具执行失败时，提供有意义的错误信息
3. **重试机制**: 对于可能失败的外部API调用，实现重试逻辑

### 性能优化

1. **减少依赖**: 避免规则依赖过多的上下文键
2. **条件优化**: 优化匹配条件，减少不必要的评估
3. **异步处理**: 充分利用异步特性，避免阻塞操作

## 常见问题

### 规则不触发

检查以下几点：
- 确保depend_ctx_key正确设置
- 检查match_condition表达式是否正确
- 验证上下文中是否有预期的数据

### 工具执行失败

可能的原因：
- 工具参数配置错误
- 外部API调用失败
- 工具实现中的错误

### 自定义工具注册问题

确保：
- 工具类正确继承Tool基类
- 实现了run方法
- 在使用前注册到ToolCenter

### 上下文数据访问

在规则条件和提示模板中：
- 使用`ctx.get('key')`访问上下文数据
- 对于嵌套数据，可以使用`ctx.get('parent.child')`
- 在条件表达式中检查键是否存在：`'key' in ctx`
