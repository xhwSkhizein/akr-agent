"""
工具基类和注册表
"""

import functools
import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Type, Union
from docstring_parser import parse
from typing import get_origin, get_args


def _get_json_type_info(annotation) -> Dict[str, Any]:
    """
    将 Python 类型注解映射到 JSON schema 类型信息（支持泛型）
    返回示例：
    - 普通类型: {"type": "integer"}
    - 泛型 list: {"type": "array", "items": {"type": "string"}}
    """
    # 无类型注解时默认返回 string（可根据需求调整）
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    # 处理泛型类型（如 list[str], dict[str, int]）
    origin = get_origin(annotation)
    args = get_args(annotation)

    # -------------------- 处理 list 泛型 --------------------
    if origin is list:
        if args:  # list[str] → {"type": "array", "items": {"type": "string"}}
            items_type = _get_json_type_info(args[0])
            return {"type": "array", "items": items_type}
        else:  # list → {"type": "array"}（无元素类型信息）
            return {"type": "array"}

    # -------------------- 处理 dict 泛型 --------------------
    if origin is dict:
        if (
            len(args) >= 2
        ):  # dict[str, int] → {"type": "object", "properties": ...}（简化处理）
            return {
                "type": "object"
            }  # 实际可扩展为更细粒度的 properties，但 OpenAI 通常接受 object
        else:
            return {"type": "object"}

    # -------------------- 处理内置类型 --------------------
    type_mapping = {
        int: "integer",
        float: "number",
        bool: "boolean",
        str: "string",
        dict: "object",
        list: "array",
        tuple: "array",  # 简化处理为 array
    }
    for py_type, json_type in type_mapping.items():
        if annotation is py_type:
            return {"type": json_type}

    # -------------------- 处理自定义类 --------------------
    # 自定义类默认视为 object（可根据需求扩展，如检查是否为 Pydantic 模型）
    return {"type": "object"}


class Tool(ABC):
    """
    工具抽象基类
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, *args, **kwargs) -> AsyncGenerator[str, None]:
        """
        工具的基础接口，所有工具都应该实现这个接口
        返回一个异步生成器，用于流式返回结果
        """
        raise NotImplementedError


class ToolCenter:
    """
    工具注册表，用于管理和访问可用工具
    """

    _tools: Dict[str, Union[Tool, Callable]] = {}

    @staticmethod
    def register(
        tool: Union[Tool, Callable, Type[Tool]], name: Optional[str] = None
    ) -> None:
        """
        注册工具

        Args:
            tool: 工具实例、函数或工具类
            name: 工具名称，如果为 None 则使用工具的 name 属性或函数名
        """
        if isinstance(tool, type) and issubclass(tool, Tool):
            # 如果是工具类，实例化它
            tool_instance = tool()
            tool_name = name or tool_instance.name or tool.__name__
            ToolCenter._tools[tool_name] = tool_instance
            logging.info(f"注册工具类: {tool_name}")

        elif isinstance(tool, Tool):
            # 如果是工具实例
            tool_name = name or tool.name or tool.__class__.__name__
            ToolCenter._tools[tool_name] = tool
            logging.info(f"注册工具实例: {tool_name}")

        elif callable(tool):
            # 如果是函数
            tool_name = name or tool.__name__
            ToolCenter._tools[tool_name] = tool
            logging.info(f"注册工具函数: {tool_name}")

        else:
            raise TypeError(f"不支持的工具类型: {type(tool)}")

    @staticmethod
    def get(name: str) -> Optional[Union[Tool, Callable]]:
        """
        获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例或函数，如果不存在则返回 None
        """
        return ToolCenter._tools.get(name)

    @staticmethod
    @functools.lru_cache(maxsize=1000)
    def list_tools() -> List[str]:
        """
        列出所有可用工具名称

        Returns:
            工具名称列表
        """
        return list(ToolCenter._tools.keys())

    @staticmethod
    @functools.lru_cache(maxsize=1000)
    def get_definition(name: str) -> Optional[Dict[str, Any]]:
        """
        动态构建 OpenAI function call 工具定义（优化版）
        """
        tool = ToolCenter.get(name)
        if tool is None:
            return None

        # 1. 获取可调用对象（优先使用 run 方法，否则直接使用工具对象）
        func: Callable = tool.run if hasattr(tool, "run") else tool
        if not callable(func):
            return None

        # 2. 解包装饰器（如果函数被装饰器包裹，获取原始函数）
        try:
            original_func = inspect.unwrap(func)  # 处理装饰器
            sig = inspect.signature(original_func)
        except ValueError:
            sig = inspect.signature(func)  # 无法解包时使用当前函数签名

        # 3. 解析 docstring 中的参数描述（支持多种风格）
        docstring = inspect.getdoc(func) or ""
        parsed_doc = parse(docstring)  # 解析后的 docstring 对象
        param_docs = {
            p.arg_name: p.description for p in parsed_doc.params
        }  # 参数名到描述的映射

        # 4. 构建 parameters 结构
        properties: Dict[str, Dict[str, Any]] = {}
        required: list[str] = []

        for pname, param in sig.parameters.items():
            # 跳过特殊参数（self/cls/args/kwargs）
            if pname in ("self", "cls", "args", "kwargs"):
                continue

            # -------------------- 类型推断 --------------------
            annotation = param.annotation
            json_type_info = _get_json_type_info(
                annotation
            )  # 获取 JSON schema 类型信息（支持泛型）

            # -------------------- 参数描述 --------------------
            # 优先使用 docstring 中的参数描述，其次使用类型注解的 __doc__，最后为空
            desc = param_docs.get(pname, "")
            if not desc and hasattr(annotation, "__doc__"):
                desc = annotation.__doc__ or ""

            # -------------------- 组装 properties --------------------
            properties[pname] = {
                **json_type_info,  # 包含 "type" 或 "type"+"items"（如 array 类型）
                "description": desc.strip(),  # 去除首尾空白
            }

            # -------------------- 判断是否必填 --------------------
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        # 5. 构建最终 schema（符合 OpenAI function call 规范）
        schema = {
            "name": name,
            "description": parsed_doc.short_description
            or name,  # 使用 docstring 短描述
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required if required else None,  # 无必填时设为 None（可选）
            },
        }

        # 移除 parameters 中可能存在的 None（OpenAI 要求字段必须存在时保留）
        if schema["parameters"]["required"] is None:
            del schema["parameters"]["required"]

        return schema

    # def get_definition(name: str) -> Optional[Dict[str, Any]]:
    #     """
    #     获取工具定义
    #     """
    #     """
    #     动态构建 OpenAI function call 工具定义
    #     """
    #     tool = ToolCenter.get(name)
    #     if tool is None:
    #         return None

    #     # 1. 获取函数对象
    #     if hasattr(tool, "run"):
    #         func = tool.run
    #     elif callable(tool):
    #         func = tool
    #     else:
    #         return None

    #     # 2. 获取签名
    #     sig = inspect.signature(func)
    #     params = []
    #     properties = {}
    #     required = []
    #     for pname, param in sig.parameters.items():
    #         if pname in ("self", "cls", "args", "kwargs"):
    #             continue
    #         # 类型推断
    #         ptype = "string"
    #         if param.annotation in (int, "int"):
    #             ptype = "integer"
    #         elif param.annotation in (float, "float"):
    #             ptype = "number"
    #         elif param.annotation in (bool, "bool"):
    #             ptype = "boolean"
    #         elif param.annotation in (dict, "dict"):
    #             ptype = "object"
    #         elif param.annotation in (list, "list"):
    #             ptype = "array"
    #         # 参数描述
    #         desc = ""
    #         if param.annotation and hasattr(param.annotation, "__doc__"):
    #             desc = param.annotation.__doc__ or ""
    #         properties[pname] = {"type": ptype, "description": desc}
    #         if param.default is inspect.Parameter.empty:
    #             required.append(pname)

    #     # 3. 获取描述
    #     doc = func.__doc__ or ""
    #     schema = {
    #         "name": name,
    #         "description": doc.strip().split("\n")[0] if doc else name,
    #         "parameters": {
    #             "type": "object",
    #             "properties": properties,
    #             "required": required,
    #         },
    #     }
    #     return schema

    @staticmethod
    async def run_tool(name: str, *args, **kwargs) -> AsyncGenerator[str, None]:
        """
        运行指定工具

        Args:
            name: 工具名称
            *args: 位置参数
            **kwargs: 关键字参数

        Yields:
            工具执行的结果流

        Raises:
            ValueError: 当工具不存在时抛出
            TypeError: 当工具类型不支持时抛出
        """
        tool = ToolCenter.get(name)

        if tool is None:
            raise ValueError(f"工具不存在: {name}")

        if isinstance(tool, Tool):
            # 如果是工具实例，调用其 run 方法
            async for chunk in tool.run(*args, **kwargs):
                yield chunk

        elif inspect.isasyncgenfunction(tool):
            # 如果是异步生成器函数
            async for chunk in tool(*args, **kwargs):
                yield chunk

        elif inspect.iscoroutinefunction(tool):
            # 如果是异步函数，将其结果作为单个 chunk 返回
            result = await tool(*args, **kwargs)
            yield str(result)

        else:
            raise TypeError(
                f"不支持的工具类型: {type(tool)}，工具必须是 Tool 实例、异步生成器函数或异步函数"
            )
