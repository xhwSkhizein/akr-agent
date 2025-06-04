# AKR-Agent 项目结构与架构

## 项目概述

AKR-Agent 是一个灵活的基于规则的 AI Agent 框架，旨在帮助开发者快速构建和部署智能代理。该框架支持动态规则配置、工具注册和上下文管理，使开发者能够轻松创建各种类型的智能代理应用。

## 包结构

```
akr_agent/
├── __init__.py                # 包入口点，导出主要接口
├── _version.py                # 版本信息（由 setuptools_scm 自动生成）
├── agent.py                   # Agent 核心类
├── agent_config_engine.py     # Agent 配置引擎
├── context_manager.py         # 上下文管理器
├── dispatcher.py              # 动态调度器
├── event_bus.py               # 事件总线
├── libs/                      # 辅助库
│   └── ...
├── llm/                       # LLM 相关模块
│   └── ...
├── observable_ctx.py          # 可观察上下文
├── output_stream_manager.py   # 输出流管理器
├── rule_config.py             # 规则配置
├── rule_registery.py          # 规则注册表
├── rule_task.py               # 规则任务
├── task_executor.py           # 任务执行器
├── task_manager.py            # 任务管理器
├── task_state.py              # 任务状态
├── tools/                     # 工具模块
│   ├── __init__.py
│   ├── base.py                # 工具基类和注册表
│   ├── tool_llm.py            # LLM 调用工具
│   ├── tool_search.py         # 搜索工具
│   └── ...
├── utils.py                   # 工具函数
└── workspace_manager.py       # 工作区管理器
```

## 核心组件

### Agent

`Agent` 是框架的核心类，负责协调各个组件工作，处理用户输入并生成响应。它通过 `AgentConfigEngine` 加载配置，使用 `ContextManager` 管理上下文，并通过 `DynamicDispatcher` 调度任务。

### 规则系统

规则系统是 AKR-Agent 的核心特性，它允许开发者通过配置文件定义代理的行为规则：

- `rule_config.py`: 定义规则配置结构
- `rule_registery.py`: 管理规则注册
- `rule_task.py`: 规则任务执行

### 工具系统

工具系统提供了扩展 Agent 能力的机制：

- `tools/base.py`: 定义工具基类和注册表
- 各种预定义工具：LLM 调用、搜索等

### 上下文管理

- `context_manager.py`: 管理 Agent 运行时的上下文
- `observable_ctx.py`: 提供可观察的上下文对象

### 任务管理

- `task_manager.py`: 管理任务的创建和执行
- `task_executor.py`: 执行具体任务
- `task_state.py`: 定义任务状态

## 配置系统

Agent 配置采用 YAML 格式，包括：

- `meta.yaml`: Agent 元数据
- `system_prompt.yaml`: 系统提示
- `rules/*.yaml`: 规则配置

## 使用流程

1. 创建 Agent 实例，指定配置目录
2. 注册所需工具
3. 调用 `run_dynamic` 方法处理用户输入
4. 获取异步生成的响应

## 扩展点

1. 自定义工具：继承 `Tool` 基类实现新工具
2. 自定义规则：创建新的规则配置文件
3. 自定义 Agent：通过配置文件定制 Agent 行为
