"""
LLM 客户端基类和响应类型
"""

import json
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union


class LLMResponse:
    """
    LLM 响应类，包含完整响应和流式响应的处理
    """
    
    def __init__(self, content: str = "", is_json: bool = False):
        """
        初始化 LLM 响应
        
        Args:
            content: 响应内容
            is_json: 响应是否为 JSON 格式
        """
        self.content = content
        self.is_json = is_json
        self._parsed_json: Optional[Dict[str, Any]] = None
        
        if is_json and content:
            try:
                self._parsed_json = json.loads(content)
            except json.JSONDecodeError:
                self.is_json = False
    
    @property
    def json(self) -> Optional[Dict[str, Any]]:
        """
        获取解析后的 JSON 数据
        
        Returns:
            解析后的 JSON 数据，如果不是 JSON 则返回 None
        """
        if not self.is_json:
            return None
            
        if self._parsed_json is None and self.content:
            try:
                self._parsed_json = json.loads(self.content)
            except json.JSONDecodeError:
                return None
                
        return self._parsed_json
    
    def __str__(self) -> str:
        return self.content


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
