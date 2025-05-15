# DeepSea Agent API 参考文档

本文档提供了DeepSea Agent框架的API参考，包括主要类和方法的详细说明。

## 目录

- [Agent](#agent)
- [ObservableCtx](#observablectx)
- [EventBus](#eventbus)
- [RuleDispatcher](#ruledispatcher)
- [RuleTask](#ruletask)
- [ToolCenter](#toolcenter)
- [Tool](#tool)
- [LLMCallTool](#llmcalltool)
- [OpenAIClient](#openaiclient)
- [AgentConfigEngine](#agentconfigengine)
- [配置类](#配置类)

## Agent

`Agent` 是框架的主要入口点，负责初始化和协调各个组件。

### 构造函数

```python
def __init__(self, config_dir: str)
```

**参数**:
- `config_dir`: 配置目录路径，包含meta.yaml、system_prompt.yaml和rules目录

### 方法

#### run_dynamic

```python
async def run_dynamic(self, user_input: str) -> AsyncGenerator[str, None]
```

**参数**:
- `user_input`: 用户输入的文本

**返回**:
- 异步生成器，生成响应文本片段

**说明**:
- 处理用户输入并生成响应
- 将用户输入设置到上下文
- 将用户输入添加到对话历史
- 从规则调度器获取输出流

## ObservableCtx

`ObservableCtx` 是一个可观察的上下文对象，当数据变化时会通知订阅者。

### 构造函数

```python
def __init__(self, event_bus: EventBus, **kwargs)
```

**参数**:
- `event_bus`: 事件总线实例
- `**kwargs`: 初始上下文数据

### 方法

#### set

```python
async def set(self, key: str, value: Any) -> None
```

**参数**:
- `key`: 键名
- `value`: 值

**说明**:
- 设置上下文中的值
- 发布ctx_changed事件

#### append

```python
async def append(self, key: str, value: Any) -> None
```

**参数**:
- `key`: 键名
- `value`: 要追加的值

**说明**:
- 将值追加到上下文中的列表
- 如果键不存在或不是列表，则抛出异常
- 发布ctx_changed事件

#### get

```python
def get(self, key: str, default: Optional[Any] = None) -> Any
```

**参数**:
- `key`: 键名
- `default`: 默认值，当键不存在时返回

**返回**:
- 键对应的值，如果不存在则返回默认值

#### to_dict

```python
def to_dict(self) -> Dict[str, Any]
```

**返回**:
- 上下文的字典表示

## EventBus

`EventBus` 实现了发布-订阅模式，用于组件间的解耦通信。

### 构造函数

```python
def __init__(self)
```

### 方法

#### subscribe

```python
def subscribe(self, event_type: str, callback: Callable) -> None
```

**参数**:
- `event_type`: 事件类型
- `callback`: 回调函数，当事件发布时调用

**说明**:
- 注册事件订阅
- 回调函数应该是异步函数

#### publish

```python
async def publish(self, event_type: str, **event_data) -> None
```

**参数**:
- `event_type`: 事件类型
- `**event_data`: 事件数据

**说明**:
- 发布事件
- 调用所有订阅了该事件类型的回调函数

## RuleDispatcher

`RuleDispatcher` 负责根据上下文变化评估规则条件，并调度符合条件的规则任务执行。

### 构造函数

```python
def __init__(self, initial_rules: List[RuleConfig], event_bus: EventBus, ctx: ObservableCtx)
```

**参数**:
- `initial_rules`: 初始规则配置列表
- `event_bus`: 事件总线实例
- `ctx`: 可观察上下文实例

### 方法

#### add_new_rule

```python
def add_new_rule(self, rule_config: RuleConfig, immediate: bool = False) -> str
```

**参数**:
- `rule_config`: 规则配置
- `immediate`: 是否立即检查规则条件并执行

**返回**:
- 任务ID

**说明**:
- 添加新规则
- 如果immediate为True，则立即检查规则条件并执行

#### get_output_stream

```python
async def get_output_stream(self) -> AsyncGenerator[str, None]
```

**返回**:
- 异步生成器，生成输出文本片段

**说明**:
- 提供最终输出的异步生成器
- 当没有任务正在运行，输出队列为空，且当前上下文下没有待处理的任务可以就绪时结束

#### shutdown

```python
async def shutdown(self) -> None
```

**说明**:
- 关闭调度器
- 取消所有正在运行的任务
- 清空输出队列

## RuleTask

`RuleTask` 封装了单个规则的执行逻辑，包括条件评估、工具调用和结果处理。

### 构造函数

```python
def __init__(self, rule_config: RuleConfig, task_id: str)
```

**参数**:
- `rule_config`: 规则配置
- `task_id`: 任务ID

### 方法

#### is_condition_meet

```python
def is_condition_meet(self, ctx: ObservableCtx) -> bool
```

**参数**:
- `ctx`: 可观察上下文实例

**返回**:
- 条件是否满足

**说明**:
- 评估规则条件
- 使用eval执行条件表达式

#### execute_tool

```python
async def execute_tool(self, ctx: ObservableCtx, dispatcher: RuleDispatcher) -> AsyncGenerator[str, None]
```

**参数**:
- `ctx`: 可观察上下文实例
- `dispatcher`: 规则调度器实例

**返回**:
- 异步生成器，生成工具执行结果

**说明**:
- 执行工具调用
- 处理工具调用结果
- 根据规则配置的tool_result_target决定结果处理方式

## ToolCenter

`ToolCenter` 是工具的注册表，提供工具的注册、获取和调用功能。

### 静态方法

#### register

```python
@staticmethod
def register(tool: Union[Tool, Callable, Type[Tool]], name: Optional[str] = None) -> None
```

**参数**:
- `tool`: 工具实例、函数或工具类
- `name`: 工具名称，如果为None则使用工具的name属性或函数名

**说明**:
- 注册工具到工具中心

#### get

```python
@staticmethod
def get(name: str) -> Optional[Union[Tool, Callable]]
```

**参数**:
- `name`: 工具名称

**返回**:
- 工具实例或函数，如果不存在则返回None

#### list_tools

```python
@staticmethod
def list_tools() -> List[str]
```

**返回**:
- 工具名称列表

#### get_definition

```python
@staticmethod
def get_definition(name: str) -> Optional[Dict[str, Any]]
```

**参数**:
- `name`: 工具名称

**返回**:
- 工具定义，如果不存在则返回None

**说明**:
- 动态构建OpenAI function call工具定义

#### run_tool

```python
@staticmethod
async def run_tool(name: str, *args, **kwargs) -> AsyncGenerator[str, None]
```

**参数**:
- `name`: 工具名称
- `*args`: 位置参数
- `**kwargs`: 关键字参数

**返回**:
- 异步生成器，生成工具执行结果

**说明**:
- 执行工具调用
- 支持JSON字符串参数解析

## Tool

`Tool` 是工具的抽象基类，定义了工具的接口。

### 属性

- `name`: 工具名称
- `description`: 工具描述

### 方法

#### run

```python
@abstractmethod
async def run(self, *args, **kwargs) -> AsyncGenerator[str, None]
```

**参数**:
- `*args`: 位置参数
- `**kwargs`: 关键字参数

**返回**:
- 异步生成器，生成工具执行结果

**说明**:
- 工具的基础接口，所有工具都应该实现这个接口

## LLMCallTool

`LLMCallTool` 是一个具体的工具实现，用于调用大型语言模型。

### 构造函数

```python
def __init__(self, **kwargs)
```

**参数**:
- `**kwargs`: LLM客户端参数

### 方法

#### run

```python
async def run(self, user_input: str, system_prompt: str, prompt: str, prompt_detail: str, **kwargs) -> AsyncGenerator[str, None]
```

**参数**:
- `user_input`: 用户输入
- `system_prompt`: 系统提示
- `prompt`: 提示
- `prompt_detail`: 提示详情
- `**kwargs`: 其他参数

**返回**:
- 异步生成器，生成LLM响应

**说明**:
- 执行LLM调用
- 渲染提示模板
- 构建工具定义
- 调用LLM客户端

## OpenAIClient

`OpenAIClient` 封装了与OpenAI API的交互逻辑。

### 构造函数

```python
def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini", temperature: float = 0.7, max_tokens: Optional[int] = None, **kwargs)
```

**参数**:
- `api_key`: OpenAI API密钥
- `model`: 模型名称
- `temperature`: 温度参数
- `max_tokens`: 最大令牌数
- `**kwargs`: 其他OpenAI API参数

### 方法

#### invoke_stream

```python
async def invoke_stream(self, system_prompt: str, user_input: str, **kwargs) -> AsyncGenerator[str, None]
```

**参数**:
- `system_prompt`: 系统提示
- `user_input`: 用户输入
- `**kwargs`: 其他参数

**返回**:
- 异步生成器，生成LLM响应

**说明**:
- 流式调用OpenAI API
- 处理function_call
- 支持工具调用

## AgentConfigEngine

`AgentConfigEngine` 负责从YAML文件加载和解析Agent配置。

### 静态方法

#### load

```python
@staticmethod
def load(config_dir: str) -> AgentConfig
```

**参数**:
- `config_dir`: 配置目录路径

**返回**:
- AgentConfig实例

**说明**:
- 加载meta配置
- 加载并渲染系统提示
- 加载规则配置
- 构建AgentConfig对象

## 配置类

### AgentConfig

```python
class AgentConfig(BaseModel):
    name: str
    meta: AgentMeta
    system_prompt: str
    rules: List[RuleConfig]
```

### AgentMeta

```python
class AgentMeta(BaseModel):
    name: str
    desc: str
    parameters: Optional[Dict[str, Any]] = None
```

### RuleConfig

```python
class RuleConfig(BaseModel):
    name: str
    depend_ctx_key: List[str]
    match_condition: Optional[str] = None
    prompt: str
    prompt_detail: Optional[str] = ""
    tool: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = {}
    tool_result_target: Literal["AS_CONTEXT", "DIRECT_RETURN", "NEW_RULES"]
    tool_result_key: Optional[str] = None
    auto_generated: bool = False
```

**说明**:
- `name`: 规则名称
- `depend_ctx_key`: 需要从上下文中获取的数据对应的key
- `match_condition`: 需要满足的条件，会被eval执行
- `prompt`: 此规则的定制prompt
- `prompt_detail`: 规则的更多补充prompt信息
- `tool`: 执行的工具调用名称
- `tool_params`: 需要用到的tools的参数
- `tool_result_target`: 此规则ai输出的结果输出到哪里
- `tool_result_key`: 如果是AS_CONTEXT，整个AI返回的JSON使用此key保存进ctx中
- `auto_generated`: 是否自动生成的规则
