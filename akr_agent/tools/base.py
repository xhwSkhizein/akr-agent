"""
Tool base class and registry
"""

import functools
import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Type, Union
from docstring_parser import parse
from .utils import get_json_type_info


class Tool(ABC):
    """
    Tool abstract base class
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    async def run(self, *args, **kwargs) -> AsyncGenerator[str, None]:
        """
        The base interface for tools, all tools should implement this interface
        Return an async generator to stream the result
        """
        raise NotImplementedError


class ToolCenter:
    """
    Tool registry, used to manage and access available tools
    """

    _tools: Dict[str, Union[Tool, Callable]] = {}

    @staticmethod
    def register(
        tool: Union[Tool, Callable, Type[Tool], None] = None,
        *,
        name: Optional[str] = None,
    ) -> Union[
        Callable[
            [Union[Tool, Callable, Type[Tool]]], Union[Tool, Callable, Type[Tool]]
        ],
        None,
    ]:
        """
        Register a tool, supports two ways of use:
        1. As a regular method: ToolCenter.register(tool, name="tool_name")
        2. As a decorator: @ToolCenter.register or @ToolCenter.register(name="tool_name")

        Args:
            tool: Tool instance, function or tool class
            name: Tool name, if None, use tool's name attribute or function name

        Returns:
            When used as a decorator, return the decorated function or class; otherwise return None
        """
        # As a decorator usage, no parameter form: @ToolCenter.register
        if tool is not None and name is None:
            return ToolCenter._register_tool(tool, name)

        # As a decorator usage, with parameter form: @ToolCenter.register(name="tool_name")
        if tool is None:

            def decorator(
                tool_func: Union[Tool, Callable, Type[Tool]]
            ) -> Union[Tool, Callable, Type[Tool]]:
                ToolCenter._register_tool(tool_func, name)
                return tool_func

            return decorator

        # As a regular method usage: ToolCenter.register(tool, name="tool_name")
        return ToolCenter._register_tool(tool, name)

    @staticmethod
    def _register_tool(
        tool: Union[Tool, Callable, Type[Tool]], name: Optional[str] = None
    ) -> None:
        """
        Internal method for actual tool registration
        """
        if isinstance(tool, type) and issubclass(tool, Tool):
            # If it's a tool class, instantiate it
            tool_instance = tool()
            tool_name = name or tool_instance.name or tool.__name__
            ToolCenter._tools[tool_name] = tool_instance
            logging.info(f"Register tool class: {tool_name}")

        elif isinstance(tool, Tool):
            # If it's a tool instance
            tool_name = name or tool.name or tool.__class__.__name__
            ToolCenter._tools[tool_name] = tool
            logging.info(f"Register tool instance: {tool_name}")

        elif callable(tool):
            # If it's a function
            tool_name = name or tool.__name__
            ToolCenter._tools[tool_name] = tool
            logging.info(f"Register tool function: {tool_name}")

        else:
            raise TypeError(f"Unsupported tool type: {type(tool)}")

        return None

    @staticmethod
    def get(name: str) -> Optional[Union[Tool, Callable]]:
        """
        Get a tool by name

        Args:
            name: Tool name

        Returns:
            Tool instance or function, returns None if not found
        """
        return ToolCenter._tools.get(name)

    @staticmethod
    @functools.lru_cache(maxsize=1000)
    def list_tools() -> List[str]:
        """
        List all available tool names

        Returns:
            List of tool names
        """
        return list(ToolCenter._tools.keys())

    @staticmethod
    @functools.lru_cache(maxsize=1000)
    def get_definition(name: str) -> Optional[Dict[str, Any]]:
        """
        Dynamically build OpenAI function call tool definition (optimized version)
        """
        tool = ToolCenter.get(name)
        if tool is None:
            return None

        # 1. Get callable object (prefer run method, otherwise use tool object directly)
        func: Callable = tool.run if hasattr(tool, "run") else tool
        if not callable(func):
            return None

        # 2. Unwrap decorators (if function is wrapped by decorators, get the original function)
        try:
            original_func = inspect.unwrap(func)  # Unwrap decorators
            sig = inspect.signature(original_func)
        except ValueError:
            sig = inspect.signature(func)  # If cannot unwrap, use current function signature

        # 3. Parse docstring parameters (support multiple styles)
        docstring = inspect.getdoc(func) or ""
        parsed_doc = parse(docstring)  # Parsed docstring object
        param_docs = {
            p.arg_name: p.description for p in parsed_doc.params
        }  # Parameter name to description mapping

        # 4. Build parameters structure
        properties: Dict[str, Dict[str, Any]] = {}
        required: list[str] = []

        for pname, param in sig.parameters.items():
            # Skip special parameters (self/cls/args/kwargs)
            if pname in ("self", "cls", "args", "kwargs"):
                continue

            # -------------------- Type inference --------------------
            annotation = param.annotation
            json_type_info = get_json_type_info(
                annotation
            )  # Get JSON schema type information (supports generics)

            # -------------------- Parameter description --------------------
            # Prefer docstring parameter description, then type annotation __doc__, finally empty
            desc = param_docs.get(pname, "")
            if not desc and hasattr(annotation, "__doc__"):
                desc = annotation.__doc__ or ""

            # -------------------- Assemble properties --------------------
            properties[pname] = {
                **json_type_info,  # Contains "type" or "type"+"items" (e.g., array type)
                "description": desc.strip(),  # Remove leading and trailing whitespace
            }

            # -------------------- Determine if required --------------------
            if param.default is inspect.Parameter.empty:
                required.append(pname)

        # 5. Build final schema (OpenAI function call specification)
        schema = {
            "name": name,
            "description": parsed_doc.short_description
            or name,  # Use docstring short description
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required if required else None,  # Set to None if no required parameters (optional)
            },
        }

        # Remove possible None in parameters (OpenAI requires fields to be present)
        if schema["parameters"]["required"] is None:
            del schema["parameters"]["required"]

        return schema

    @staticmethod
    async def run_tool(name: str, *args, **kwargs) -> AsyncGenerator[str, None]:
        """
        Run a specified tool

        Args:
            name: Tool name
            *args: Positional arguments
            **kwargs: Keyword arguments

        Yields:
            Result stream from the tool execution

        Raises:
            ValueError: When the tool does not exist
            TypeError: When the tool type is not supported
        """
        tool = ToolCenter.get(name)

        if tool is None:
            raise ValueError(f"Tool not found: {name}")

        if isinstance(tool, Tool):
            # If it's a tool instance, call its run method
            async for chunk in tool.run(*args, **kwargs):
                yield chunk

        elif inspect.isasyncgenfunction(tool):
            # If it's an async generator function
            async for chunk in tool(*args, **kwargs):
                yield chunk

        elif inspect.iscoroutinefunction(tool):
            # If it's an async function, return its result as a single chunk
            result = await tool(*args, **kwargs)
            yield str(result)

        else:
            raise TypeError(f"Unsupported tool type: {type(tool)}")
