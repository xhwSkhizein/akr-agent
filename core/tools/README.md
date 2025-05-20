# 工具系统 (Tools System)

本目录包含 AKR Agent 框架的工具系统实现，提供了一套灵活、可扩展的工具注册和调用机制。

## 核心组件

### 1. 工具基类 (`Tool`)

`Tool` 是所有工具的抽象基类，定义了工具的基本接口和属性：

- **name**: 工具名称
- **description**: 工具描述
- **run()**: 工具执行方法，返回异步生成器用于流式输出结果

```python
class Tool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, *args, **kwargs) -> AsyncGenerator[str, None]:
        """工具的基础接口，所有工具都应该实现这个接口"""
        raise NotImplementedError
```

### 2. 工具注册中心 (`ToolCenter`)

`ToolCenter` 是工具的注册表，负责管理和访问所有可用工具：

- **register()**: 注册工具（支持工具类、工具实例和函数）
- **get()**: 获取指定名称的工具
- **list_tools()**: 列出所有可用工具名称
- **get_definition()**: 动态构建符合 OpenAI function call 规范的工具定义
- **run_tool()**: 运行指定工具并返回结果流

## 类型映射与工具定义

系统实现了 Python 类型注解到 JSON Schema 类型的自动映射（`_get_json_type_info` 函数），支持：

- 基本类型（int、float、bool、str 等）
- 复合类型（list、dict 等）
- 泛型类型（如 `list[str]`、`dict[str, int]` 等）

## 工具注册机制

工具注册支持多种形式：

1. **工具类注册**：注册 `Tool` 的子类
2. **工具实例注册**：注册 `Tool` 的实例
3. **函数注册**：直接注册异步函数或异步生成器函数

## 工具执行流程

1. 通过 `ToolCenter.get()` 获取工具
2. 根据工具类型选择合适的执行方式：
   - `Tool` 实例：调用其 `run()` 方法
   - 异步生成器函数：直接调用
   - 异步函数：调用并将结果作为单个块返回

## 特性与优势

- **异步流式输出**：所有工具支持异步生成器接口，实现流式输出
- **自动类型推断**：从 Python 类型注解自动生成 JSON Schema
- **文档自动提取**：从 docstring 自动提取参数描述
- **灵活的注册机制**：支持多种形式的工具注册
- **兼容 OpenAI Function Call**：自动生成符合 OpenAI 规范的工具定义

## 使用示例

```python
# 注册工具类
@ToolCenter.register
class MyTool(Tool):
    name = "my_tool"
    description = "这是一个示例工具"
    
    async def run(self, param1: str, param2: int = 0) -> AsyncGenerator[str, None]:
        """
        工具描述
        
        Args:
            param1: 参数1的描述
            param2: 参数2的描述
        """
        yield f"处理参数: {param1}, {param2}"
        # 处理逻辑...
        yield "处理完成"

# 注册函数工具
@ToolCenter.register
async def my_function(text: str) -> AsyncGenerator[str, None]:
    """处理文本
    
    Args:
        text: 要处理的文本
    """
    yield f"处理文本: {text}"
    # 处理逻辑...
    yield "处理完成"

# 运行工具
async for chunk in ToolCenter.run_tool("my_tool", param1="hello", param2=42):
    print(chunk)
```
