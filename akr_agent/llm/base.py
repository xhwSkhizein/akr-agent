"""
LLM 客户端基类
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMClient(ABC):
    """
    LLM 客户端抽象基类
    """
    
    
    @abstractmethod
    async def invoke_stream(self, system_prompt: str, user_input: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        流式调用 LLM 并返回响应流
        
        Args:
            system_prompt: 系统提示词
            user_input: 用户输入
            **kwargs: 其他参数
            
        Returns:
            异步生成器，产生响应片段
        """
        pass
