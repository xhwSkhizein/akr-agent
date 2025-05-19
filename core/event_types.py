"""
事件类型定义模块

定义系统中使用的所有事件类型常量，用于事件驱动模型
"""
from enum import Enum


class EventType:
    """事件类型常量"""
    # 上下文变化事件
    CTX_CHANGED = "ctx_changed"
    
    # 任务状态变化事件
    TASK_CHANGED = "task_changed"
    
    # 流状态变化事件
    STREAM_CHANGED = "stream_changed"


class ChangeType:
    """变化类型常量，用于细分事件类型"""
    # 任务变化类型
    TASK_CREATED = "created"
    TASK_STATE_CHANGED = "state_changed"
    TASK_COMPLETED = "completed"
    TASK_FAILED = "failed"
    
    # 流变化类型
    STREAM_REGISTERED = "registered"
    STREAM_EXHAUSTED = "exhausted"
    STREAM_ERROR = "error"
