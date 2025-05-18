from pydantic import BaseModel
from typing import Optional, Dict, Any


class ResponseChunk(BaseModel):
    """响应块，用于结构化输出任务执行结果"""
    
    content: str
    rule_name: str
    rule_id: str
    task_id: str
    rule_priority: int = 0
    
    def __str__(self) -> str:
        return f"{self.rule_name} {self.rule_id} {self.task_id} {self.rule_priority} {self.content}"
    
    def dict(self) -> Dict[str, Any]:
        """返回对象的字典表示，用于JSON序列化"""
        return {
            "content": self.content,
            "rule_name": self.rule_name,
            "rule_id": self.rule_id,
            "task_id": self.task_id,
            "rule_priority": self.rule_priority
        }
    
    def __iter__(self):
        """使对象可迭代，支持dict()转换"""
        yield from self.dict().items()
    
    def keys(self):
        """返回对象的键，支持dict()转换"""
        return self.dict().keys()