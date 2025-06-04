
from typing import Dict, Optional, List
import asyncio
import time
import logging
import uuid

from .context_manager import ContextManager
from .task_executor import TaskExecutor
from .event_bus import EventType, RealTimeEvent
from .output_stream_manager import OutputStreamManager
from .task_state import TaskState, TaskInfo
from .rule_config import RuleConfig



valid_transitions = {
    TaskState.PENDING: [TaskState.READY, TaskState.FAILED],
    TaskState.READY: [TaskState.EXECUTING, TaskState.FAILED],
    TaskState.EXECUTING: [TaskState.COMPLETED, TaskState.FAILED],
    TaskState.COMPLETED: [],  # Terminal state, cannot transition
    TaskState.FAILED: [],  # Terminal state, cannot transition
}


class TaskManager:
    """
    Task manager, responsible for task creation, state management, and lifecycle monitoring
    """

    def __init__(
        self,
        context_manager: ContextManager,
        executor: TaskExecutor,
        output_manager: OutputStreamManager,
        logger: logging.Logger,
        max_concurrent_tasks: int = 10,
        timeout_detection_time: int = 60,
    ):
        self._context_manager: ContextManager = context_manager
        self._executor: TaskExecutor = executor
        self._output_manager: OutputStreamManager = output_manager
        self._logger: logging.Logger = logger
        self._tasks: Dict[str, TaskInfo] = {}  # task_id -> task_info
        self._task_semaphore = asyncio.Semaphore(max_concurrent_tasks)
        # Task monitor
        self._monitor_task: Optional[asyncio.Task] = None
        # Timeout detection
        self._timeout_detection_time: int = timeout_detection_time
        # Start monitor task
        self._start_monitor()

        # Subscribe to task events
        self._context_manager.subscribe(EventType.RULE_TASK_EXECUTING, self._handle_task_executing)
        self._context_manager.subscribe(EventType.RULE_TASK_COMPLETED, self._handle_task_completed)
        self._context_manager.subscribe(EventType.RULE_TASK_FAILED, self._handle_task_failed)
        self._context_manager.subscribe(EventType.RULE_TASK_CANCELLED, self._handle_task_cancelled)

    async def _handle_task_executing(self, event: RealTimeEvent):
        self._logger.info(f"Task {event.data['task_id']} is executing")

    async def _handle_task_completed(self, event: RealTimeEvent):
        self.release_execution_slot()
        self._logger.info(f"Task {event.data['task_id']} is completed")

    async def _handle_task_failed(self, event: RealTimeEvent):
        self.release_execution_slot()
        self._logger.info(f"Task {event.data['task_id']} is failed")

    async def _handle_task_cancelled(self, event: RealTimeEvent):
        self.release_execution_slot()
        self._logger.info(f"Task {event.data['task_id']} is cancelled")


    def generate_task_id(self, rule_id: str) -> str:
        """Generate a unique task ID"""
        return f"task_{rule_id}_{str(uuid.uuid4())[:8]}"

    async def create_task_and_schedule(self, rule_id: str, rule_config: RuleConfig) -> str:
        """Create a new task"""
        task_id = self.generate_task_id(rule_id)
        new_task: TaskInfo = TaskInfo(
            task_id=task_id,
            rule_id=rule_id,
            rule_config=rule_config,
            state=TaskState.PENDING,
            success=False,
            error=None,
            execution_time=None,
            response_full=None,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._tasks[task_id] = new_task
        # Schedule task
        await self._schedule_task(task_id)

        return task_id

    async def _schedule_task(self, task_id: str) -> None:
        """Schedule task execution"""
        # Try to acquire an execution slot
        if not await self.acquire_execution_slot():
            self._logger.info(f"Max concurrent tasks reached. Delaying task {task_id}")
            return
        if task_id not in self._tasks:
            self._logger.error(f"Task {task_id} not found, skip scheduling")
            return
        task_info = self._tasks[task_id]
        if task_info.state != TaskState.PENDING:
            self._logger.error(f"Task {task_id} is not in PENDING state, skip scheduling")
            return
        try:
            # Set task state to ready
            await self._set_task_state(task_id, TaskState.READY)
            task_info: TaskInfo = self.get_task_info(task_id)
            rule_config = task_info.rule_config
            # Get async generator
            async_generator = self._executor.run_task(task_info)
            # Register this stream with output manager
            stream_id = self._output_manager.register_stream(
                async_generator, task_info
            )

            self._logger.info(
                f"Task {task_id} (Name: {rule_config.name}) is scheduled for execution. stream_id={stream_id}"
            )
        except Exception as e:
            self._logger.error(f"Error scheduling task {task_id}: {e}")
            self.release_execution_slot()
            await self._set_task_state(task_id, TaskState.FAILED, success=False, error=str(e))
            

        
    async def _set_task_state(
        self,
        task_id: str,
        new_state: TaskState,
        success: Optional[bool] = None,
        error: Optional[str] = None,
    ) -> None:
        """Set task state"""
        if task_id not in self._tasks:
            self._logger.error(f"Task {task_id} not found")
            return

        task_info = self._tasks[task_id]
        old_state: TaskState = task_info.state

        # Check if the state transition is valid
        if not self._is_valid_state_transition(old_state, new_state):
            self._logger.error(
                f"Invalid state transition: {old_state} -> {new_state}"
            )
            return

        # Update state
        task_info.state = new_state
        if success is not None:
            task_info.success = success
        if error is not None:
            task_info.error = error
        task_info.updated_at = time.time()
        self._logger.info(
            f"Task {task_id} state changed: {old_state.value} -> {new_state.value}"
        )

        
            
    def _is_valid_state_transition(
        self, current_state: TaskState, new_state: TaskState
    ) -> bool:
        """Check if the state transition is valid"""
        return new_state in valid_transitions[current_state]

    def get_task_state(self, task_id: str) -> Optional[TaskState]:
        """Get task state"""
        if task_id not in self._tasks:
            return None
        return self._tasks[task_id].state

    def is_task_completed(self, task_id: str) -> bool:
        """Check if the task is completed"""
        state = self.get_task_state(task_id)
        return state in (TaskState.COMPLETED, TaskState.FAILED)

    def is_task_executing(self, task_id: str) -> bool:
        """Check if the task is executing"""
        return self.get_task_state(task_id) == TaskState.EXECUTING

    def is_task_ready(self, task_id: str) -> bool:
        """Check if the task is ready"""
        return self.get_task_state(task_id) == TaskState.READY

    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """Get task info"""
        return self._tasks.get(task_id)

    def get_tasks_by_rule(self, rule_id: str) -> List[str]:
        """Get all task IDs for a specific rule"""
        return [
            task_id
            for task_id, task_info in self._tasks.items()
            if task_info.rule_id == rule_id
        ]

    def get_active_tasks(self) -> List[str]:
        """Get all active task IDs"""
        return [
            task_id
            for task_id, task_info in self._tasks.items()
            if task_info.state not in (TaskState.COMPLETED, TaskState.FAILED)
        ]

    async def acquire_execution_slot(self) -> bool:
        """Acquire an execution slot"""
        try:
            # Set timeout to avoid infinite wait
            await asyncio.wait_for(self._task_semaphore.acquire(), timeout=2)
            return True
        except asyncio.TimeoutError:
            return False

    def release_execution_slot(self) -> None:
        """Release an execution slot"""
        self._task_semaphore.release()

    def get_inactive_tasks(self) -> List[str]:
        """Get inactive tasks"""
        current_time = time.time()
        return [
            task_id
            for task_id, task_info in self._tasks.items()
            if not self.is_task_completed(task_id)
            and current_time - task_info.updated_at > self._timeout_detection_time
        ]

    def _start_monitor(self) -> None:
        """
        Start monitor task
        """
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        """
        Monitor loop, check task status and potential timeouts
        """
        try:
            while True:
                await asyncio.sleep(1)  # Check every second

                # Check for inactive tasks
                active_tasks = self.get_active_tasks()
                for task_id in active_tasks:
                    if self.get_task_state(task_id) == TaskState.PENDING:
                        await self._schedule_task(task_id)
                        continue
                    
                    if time.time() - self._tasks[task_id].updated_at > self._timeout_detection_time:
                        self._logger.warning(
                            f"Task {task_id} has been inactive for {self._timeout_detection_time} seconds."
                        )
                        # Try to mark the stuck task as failed
                        if self.is_task_executing(task_id):
                            try:
                                await self._executor.cancel_task(task_id)
                                self._logger.warning(
                                        f"Marked stuck task {task_id} as FAILED, error: Timeout detected"
                                )
                            except Exception as e:
                                self._logger.error(
                                    f"Error handling stuck task {task_id}: {e}"
                                )
                        
        except asyncio.CancelledError:
            self._logger.debug("Monitor task cancelled")
        except Exception as e:
            self._logger.error(f"Error in monitor loop: {e}", exc_info=True)

    async def shutdown(self) -> None:
        """Shutdown task manager"""
        # Mark all active tasks as failed
        for task_id in self.get_active_tasks():
            await self._executor.cancel_task(task_id)

        # Cancel monitor task
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
