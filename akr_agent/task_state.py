import enum
from typing import Optional
from dataclasses import dataclass
from dataclasses_json import DataClassJsonMixin
from .rule_config import RuleConfig

class TaskState(enum.Enum):
    """
    Task state enum

    PENDING: Initial state, task is created but not ready to execute
    READY: Conditions are met, task is ready to execute
    EXECUTING: Task is executing
    COMPLETED: Task is completed
    FAILED: Task execution failed
    """
    PENDING = "pending"     # Initial state
    READY = "ready"         # Conditions are met, task is ready to execute
    EXECUTING = "executing" # Task is executing
    COMPLETED = "completed" # Task is completed
    FAILED = "failed"       # Task execution failed

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
    Task state transition error

    Raises when an invalid state transition is attempted
    """
    def __init__(self, current_state: TaskState, target_state: TaskState, message: Optional[str] = None):
        self.current_state = current_state
        self.target_state = target_state
        msg = f"Invalid state transition: {current_state.value} -> {target_state.value}"
        if message:
            msg += f": {message}"
        super().__init__(msg)
