# AKR-Agent: Agent Know Rules

[![PyPI version](https://badge.fury.io/py/akr-agent.svg)](https://badge.fury.io/py/akr-agent)
[![Python Version](https://img.shields.io/pypi/pyversions/akr-agent.svg)](https://pypi.org/project/akr-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

AKR-Agent is a flexible rule-based AI Agent framework, designed to help developers quickly build and deploy intelligent agents. The framework supports dynamic rule configuration, tool registration, and context management, making it easy for developers to create various types of intelligent agent applications.

## Installation

```bash
pip install akr-agent
```

## Quick Start

```python
import asyncio
import os
from akr_agent import Agent, ToolCenter
from akr_agent.tools.tool_llm import LLMCallTool

# Register LLM tool
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
    # Create Agent instance, specify config directory
    agent = Agent(config_dir="prompts/CoachLi/v1")
    
    # User input
    user_input = "I want to start fitness, what are the suggestions?"
    print(f"\n--- User Input ---\n{user_input}")
    
    # Run Agent and get response
    print("\n--- Agent Response ---")
    async for chunk in agent.run_dynamic(user_input):
        print(chunk.content, end="", flush=True)
    
    print("\n\n--- Done ---")

if __name__ == "__main__":
    asyncio.run(main())
```

## Architecture Design

* Advantage:
    * Agent is the core class to manage the entire process
    * DynamicDispatcher responsible for rule scheduling and execution
    * ObservableContext provides reactive context management
    * EventBus implements event-driven mechanism
    * ToolCenter provides tool registration and invocation capability


## Core Function

1. **Rule Engine**: Flexible rule system based on configuration, supports conditional matching and dynamic rule generation
2. **Context Management**: Implements observable context management, supports data change notifications
3. **Tool System**: Provides a unified interface for tool registration and invocation, supports asynchronous streaming output
4. **LLM Integration**: Wraps OpenAI API, supports streaming responses and tool calls

## Configuration System

* Manage Agent behavior using YAML configuration files, including system prompts, rule definitions, etc.
* Support Jinja2 template rendering, allowing dynamic generation of prompts based on context

### Configuration Directory Structure

```
prompts/
└── YourAgent/version_x/
    ├── meta.yaml           # Agent metadata
    ├── system_prompt.yaml  # System prompt
    └── rules/              # Rule directory
        ├── rule1.yaml      # Rule 1
        ├── rule2.yaml      # Rule 2
        └── ...             # At least one rule must be able to handle user input
```

### meta.yaml Example

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

### system_prompt.yaml Example

```yaml
content: |
  You are {{ meta.name }}, you are a {{ meta.desc }}.
  You are very willing to help users with {{ meta.parameters.skill | join(', ') }}.
  You are better at helping users with {{ meta.parameters.advantages | join(', ') }},
  but not good at helping users with {{ meta.parameters.disadvantages | join(', ') }}.
```

### Rule Configuration Example

```yaml
name: "basic_reply"
depend_ctx_key:
  - "user_input"
match_condition: "True"  # Always match
prompt: |
  Please provide a useful answer based on the user's question.
prompt_detail: |
  The user's question is: {{ user_input }}
tool: "LLMCallTool" # The tool registered in advance
tool_params:
  ctx: ["user_input"]
  config: ["prompt", "prompt_detail"]
  extra:
    - tools:
      - "ToolNameThatLLMCanUse"
tool_result_target: "DIRECT_RETURN" # Directly return to user
```



## Custom Tools

You can create custom tools by inheriting the `Tool` base class:

```python
from typing import AsyncGenerator
from akr_agent import Tool, ToolCenter

class WeatherTool(Tool):
    """Get weather information"""
    
    name = "WeatherTool"
    description = "Get weather information for a specified city"
    
    def __init__(self, api_key=None):
        self.api_key = api_key
    
    async def run(self, city: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        Get weather information for a specified city
        
        Args:
            city: City name
        """
        # Implement weather API call logic
        weather_info = f"{city} weather: sunny, temperature 25°C"
        yield weather_info

# Register tool
ToolCenter.register(tool=WeatherTool(api_key="your_weather_api_key"))
```

## Development Guide

### Install development dependencies

```bash
pip install -e ".[dev]"
```

### Run tests

```bash
python -m pytest tests
```

### Code Style

We use Black and isort to maintain consistent code style:

```bash
black akr_agent
isort akr_agent
```

### Type Checking

Use mypy for type checking:

```bash
mypy akr_agent
```

## Contribution Guide

We welcome all forms of contributions, including but not limited to:

1. Reporting issues and suggesting improvements
2. Submitting code fixes or new features
3. Improving documentation
4. Adding test cases

### Contribution Process

1. Fork the project repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Create a Pull Request

## Roadmap

- [ ] Support more LLM providers
- [ ] Add more built-in tools
- [ ] Improve error handling and recovery mechanisms
- [ ] Add more examples and documentation
- [ ] Implement caching mechanisms and performance optimization

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details