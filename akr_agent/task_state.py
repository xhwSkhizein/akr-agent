import enum
from typing import Optional
from dataclasses import dataclass
from dataclasses_json import DataClassJsonMixin
from .rule_config import RuleConfig

class TaskState(enum.Enum):
    """
    任务状态枚举

    PENDING: 初始状态，任务已创建但尚未准备好执行
    READY: 条件满足，任务准备好执行
    EXECUTING: 任务正在执行中
    COMPLETED: 任务已完成
    FAILED: 任务执行失败
    """
    PENDING = "pending"     # 初始状态
    READY = "ready"         # 条件满足，准备执行
    EXECUTING = "executing" # 正在执行
    COMPLETED = "completed" # 已完成
    FAILED = "failed"       # 执行失败

@dataclass
class TaskInfo(DataClassJsonMixin):
    task_id: str
    rule_id: str
    rule_config: RuleConfig
    state: TaskState
    success: bool
    error: Optional[str]
    execution_time: Optional[float]
    response_full: Optional[str]
    created_at: float
    updated_at: float


class TaskStateTransitionError(Exception):
    """
    任务状态转换错误

    当尝试进行无效的状态转换时抛出
    """
    def __init__(self, current_state: TaskState, target_state: TaskState, message: Optional[str] = None):
        self.current_state = current_state
        self.target_state = target_state
        msg = f"无效的状态转换: {current_state.value} -> {target_state.value}"
        if message:
            msg += f": {message}"
        super().__init__(msg)
