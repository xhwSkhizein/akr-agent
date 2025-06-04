"""
LLM client base class
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMClient(ABC):
    """
    LLM client abstract base class
    """
    
    
    @abstractmethod
    async def invoke_stream(self, system_prompt: str, user_input: str, **kwargs) -> AsyncGenerator[str, None]:
        """
        Streamly invoke LLM and return response stream
        
        Args:
            system_prompt: System prompt
            user_input: User input
            **kwargs: Other parameters
            
        Returns:
            Async generator, yield response fragments
        """
        pass
