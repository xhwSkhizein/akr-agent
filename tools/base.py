"""
工具基类和注册表
"""

import inspect
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Type, Union


class Tool(ABC):
    """
    工具抽象基类
    """
    
    name: str = ""
    description: str = ""
    
    @abstractmethod
    async def run(self, *args, **kwargs) -> Any:
        """
        运行工具
        
        Returns:
            工具执行结果
        """
        pass


class ToolRegistry:
    """
    工具注册表，用于管理和访问可用工具
    """
    
    def __init__(self):
        """
        初始化工具注册表
        """
        self._tools: Dict[str, Union[Tool, Callable]] = {}
    
    def register(self, tool: Union[Tool, Callable, Type[Tool]], name: Optional[str] = None) -> None:
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
            self._tools[tool_name] = tool_instance
            logging.info(f"注册工具类: {tool_name}")
            
        elif isinstance(tool, Tool):
            # 如果是工具实例
            tool_name = name or tool.name or tool.__class__.__name__
            self._tools[tool_name] = tool
            logging.info(f"注册工具实例: {tool_name}")
            
        elif callable(tool):
            # 如果是函数
            tool_name = name or tool.__name__
            self._tools[tool_name] = tool
            logging.info(f"注册工具函数: {tool_name}")
            
        else:
            raise TypeError(f"不支持的工具类型: {type(tool)}")
    
    def get(self, name: str) -> Optional[Union[Tool, Callable]]:
        """
        获取工具
        
        Args:
            name: 工具名称
            
        Returns:
            工具实例或函数，如果不存在则返回 None
        """
        return self._tools.get(name)
    
    def list_tools(self) -> List[str]:
        """
        列出所有可用工具名称
        
        Returns:
            工具名称列表
        """
        return list(self._tools.keys())
    
    async def run_tool(self, name: str, *args, **kwargs) -> Any:
        """
        运行指定工具
        
        Args:
            name: 工具名称
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            工具执行结果
            
        Raises:
            ValueError: 当工具不存在时抛出
        """
        tool = self.get(name)
        
        if tool is None:
            raise ValueError(f"工具不存在: {name}")
            
        if isinstance(tool, Tool):
            # 如果是工具实例，调用其 run 方法
            return await tool.run(*args, **kwargs)
            
        elif callable(tool):
            # 如果是函数，直接调用
            if inspect.iscoroutinefunction(tool):
                # 如果是异步函数
                return await tool(*args, **kwargs)
            else:
                # 如果是同步函数
                return tool(*args, **kwargs)
                
        else:
            raise TypeError(f"不支持的工具类型: {type(tool)}")
