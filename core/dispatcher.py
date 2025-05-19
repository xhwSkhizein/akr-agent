import asyncio
import logging
import uuid
import time
from typing import List, Dict, Set, Any, AsyncGenerator, Optional, Tuple
from collections import defaultdict

from core.rule_config import RuleConfig
from core.event_bus import EventType, EventBus
from core.observable_ctx import ObservableCtx
from core.rule_task import RuleTask
from core.task_state import TaskState
from core.output_stream import OutputStreamManager, StreamMetadata, OutputChunk


logger = logging.getLogger(__name__)


class RuleIndex:
    """规则索引结构，用于加速规则匹配"""

    def __init__(self):
        self._key_to_rules = defaultdict(set)  # ctx_key -> {rule_ids}

    def add_rule(self, rule_id: str, depend_keys: List[str]) -> None:
        """添加规则到索引"""
        for key in depend_keys:
            self._key_to_rules[key].add(rule_id)

    def remove_rule(self, rule_id: str, depend_keys: List[str]) -> None:
        """从索引中移除规则"""
        for key in depend_keys:
            if rule_id in self._key_to_rules[key]:
                self._key_to_rules[key].remove(rule_id)

    def get_rules_for_key(self, key: str) -> Set[str]:
        """获取依赖指定键的所有规则ID"""
        return self._key_to_rules.get(key, set())


class PriorityTaskQueue:
    """优先级任务队列，用于高效调度任务"""

    def __init__(self):
        self._queue: List[Tuple[int, str]] = []  # [(priority, task_id)]

    def put(self, priority: int, task_id: str) -> None:
        """添加任务到队列，按优先级排序（高优先级在前）"""
        self._queue.append((-priority, task_id))  # 负优先级使高优先级在前
        self._queue.sort(key=lambda x: x[0])  # 按优先级排序

    def get(self) -> Optional[str]:
        """获取优先级最高的任务ID"""
        if not self._queue:
            return None
        _, task_id = self._queue.pop(0)
        return task_id

    def __len__(self) -> int:
        """获取队列长度"""
        return len(self._queue)


class RuleDispatcher:

    def __init__(
        self,
        initial_rules: List[RuleConfig] = None,
        event_bus: Optional[EventBus] = None,
        ctx: Optional[ObservableCtx] = None,
        max_concurrent_tasks: int = 10,
        deadlock_detection_time: int = 30,
    ):
        """初始化规则调度器"""
        self._event_bus = event_bus or EventBus()
        self._ctx = ctx or ObservableCtx()

        # 规则和任务管理
        self._rule_configs: Dict[str, RuleConfig] = (
            {}
        )  # 存储所有规则配置: rule_id -> RuleConfig
        self._tasks: Dict[str, RuleTask] = {}  # 存储已创建的任务: task_id -> RuleTask
        self._active_task_executions: Set[asyncio.Task] = (
            set()
        )  # 存储活动的任务执行协程

        # 并发控制
        self._max_concurrent_tasks = max_concurrent_tasks
        self._task_semaphore = asyncio.Semaphore(max_concurrent_tasks)

        # 规则优先级和活动跟踪
        self._rule_priorities: Dict[str, int] = {}  # 规则优先级: rule_id -> priority
        # 任务最后活动时间: task_id -> timestamp
        self._task_last_activity: Dict[str, float] = (
            {}
        )  # 任务最后活动时间: task_id -> timestamp

        # 死锁检测
        self._deadlock_detection_time = deadlock_detection_time

        # 输出流管理器
        self._output_manager = OutputStreamManager(event_bus=self._event_bus)

        # 规则索引结构 - 优化1：加速规则匹配
        self._rule_index = RuleIndex()

        # 优先级任务队列 - 优化2：高效任务调度
        self._task_priority_queue = PriorityTaskQueue()

        # 订阅上下文变化事件
        self._event_bus.subscribe(EventType.CTX_CHANGED, self._handle_ctx_changed)

        # 初始化规则
        if initial_rules:
            for rule_config in initial_rules:
                self.add_new_rule(rule_config)

    def _generate_rule_id(self, rule_name: str) -> str:
        """生成唯一的规则ID"""
        return f"{rule_name}_{str(uuid.uuid4())[:8]}"

    def _generate_task_id(self, rule_id: str) -> str:
        """生成唯一的任务ID"""
        return f"task_{rule_id}_{str(uuid.uuid4())[:8]}"

    def add_new_rule(self, rule_config: RuleConfig, immediate: bool = False) -> str:
        """添加新规则，返回任务ID"""
        rule_id = self._generate_rule_id(rule_config.name)

        # 存储规则配置
        self._rule_configs[rule_id] = rule_config

        # 设置优先级（如果有）
        priority = getattr(rule_config, "priority", 0)
        self._rule_priorities[rule_id] = priority

        # 添加到规则索引 - 优化1：加速规则匹配
        self._rule_index.add_rule(rule_id, rule_config.depend_ctx_key)

        logger.debug(
            f"Added new rule: {rule_id} (Name: {rule_config.name}, "
            f"Depend_ctx_key: {rule_config.depend_ctx_key}, "
            f"Condition: {rule_config.match_condition}, Priority: {priority})"
        )

        # 如果需要立即检查，则检查条件并在满足时创建并调度任务
        if immediate:
            asyncio.create_task(self._check_and_create_task_if_needed(rule_id))

        return rule_id

    async def _handle_ctx_changed(self, event_data: Dict[str, Any]) -> None:
        """处理上下文变化事件"""
        changed_key = event_data["key"]
        changed_value = event_data["value"]
        old_value = event_data["old_value"]

        logger.info(
            f"Ctx changed: key='{changed_key}', changed value: {changed_value}, old value: {old_value}"
        )

        # 使用规则索引快速找出依赖于此键的所有规则 - 优化1：加速规则匹配
        dependent_rule_ids = self._rule_index.get_rules_for_key(changed_key)
        logger.info(
            f"Found {len(dependent_rule_ids)} rules depending on key '{changed_key}'"
        )

        # 重置优先级队列
        self._task_priority_queue = PriorityTaskQueue()

        # 将依赖规则按优先级添加到队列
        for rule_id in dependent_rule_ids:
            if rule_id in self._rule_configs:
                # 更新最后活动时间
                self._task_last_activity[rule_id] = time.time()

                # 获取规则优先级
                priority = self._rule_priorities.get(rule_id, 0)

                # 添加到优先级队列 - 优化2：高效任务调度
                self._task_priority_queue.put(priority, rule_id)
                logger.debug(
                    f"Rule {rule_id} added to priority queue with priority {priority}"
                )

        # 依次检查和调度任务，按优先级顺序
        while len(self._task_priority_queue) > 0:
            rule_id = self._task_priority_queue.get()
            if rule_id:
                await self._check_and_create_task_if_needed(rule_id)

    async def _check_and_create_task_if_needed(self, rule_id: str) -> None:
        """检查规则条件，如果满足则创建并调度任务"""
        # 获取规则配置
        rule_config = self._rule_configs.get(rule_id)
        if not rule_config:
            logger.warning(f"Rule config for rule {rule_id} not found.")
            return

        # 使用互斥锁防止竞态条件
        # 创建一个规则特定的锁，如果不存在则创建
        if not hasattr(self, "_rule_locks"):
            self._rule_locks = {}

        if rule_id not in self._rule_locks:
            self._rule_locks[rule_id] = asyncio.Lock()

        # 使用锁确保同一规则的检查和创建是原子的
        async with self._rule_locks[rule_id]:
            # 检查是否有该规则的任务正在执行
            active_tasks = [
                task
                for task in self._tasks.values()
                if task.rule_id == rule_id and task.is_executing()
            ]
            if active_tasks:
                logger.info(
                    f"Rule {rule_id} already has active tasks. Skipping task creation."
                )
                return

            # 使用类方法检查规则条件，无需创建临时任务对象
            if not RuleTask.check_condition(
                condition=rule_config.match_condition, ctx=self._ctx
            ):
                logger.info(
                    f"Rule {rule_id} does not meet the condition. Skipping task creation."
                )
                return

            # 条件满足，创建新任务
            task_id = self._generate_task_id(rule_id)
            new_task = RuleTask(
                rule_config=rule_config,
                task_id=task_id,
                event_bus=self._event_bus,
                rule_id=rule_id,
            )
            self._tasks[task_id] = new_task

            # 记录任务创建信息
            logger.info(f"Created new task {task_id} for rule {rule_id}")

            # 记录任务最后活动时间
            self._task_last_activity[task_id] = time.time()

            # 调度任务执行
            await self._schedule_task(new_task)

    async def _schedule_task(self, task: RuleTask) -> None:
        """调度任务执行"""
        # 尝试获取并发信号量，如果已达到最大并发数，则延迟调度
        try:
            # 非阻塞尝试获取信号量
            if not self._task_semaphore.locked() or self._task_semaphore._value > 0:
                # 还有信号量可用
                await self._task_semaphore.acquire()
            else:
                # 没有信号量可用，延迟调度
                logger.debug(
                    f"Max concurrent tasks reached. Delaying task {task.task_id}"
                )
                return
        except Exception as e:
            logger.error(f"Error acquiring semaphore for task {task.task_id}: {e}")
            return

        # 设置任务状态为准备就绪
        try:
            await task.set_state(TaskState.READY)
        except Exception as e:
            logger.error(f"Error setting task {task.task_id} to READY state: {e}")
            self._task_semaphore.release()  # 释放信号量
            return

        # 设置任务状态为执行中
        try:
            await task.set_state(TaskState.EXECUTING)
        except Exception as e:
            logger.error(f"Error setting task {task.task_id} to EXECUTING state: {e}")
            self._task_semaphore.release()  # 释放信号量
            return

        logger.info(
            f"Task {task.task_id} (Name: {task.rule_config.name}) is ready. Scheduling for execution."
        )

        # 准备执行协程
        execution_coro = task.execute_tool(ctx=self._ctx, dispatcher=self)

        # 创建流元数据
        metadata = StreamMetadata(
            rule_name=task.rule_config.name,
            rule_id=task.rule_id,
            task_id=task.task_id,
            rule_priority=task.rule_config.priority,
        )

        # 向输出管理器注册此流
        stream_id = await self._output_manager.register_stream(execution_coro, metadata)

        logger.info(
            f"Task {task.task_id} (Name: {task.rule_config.name}) is scheduled for execution. stream_id={stream_id}"
        )

        # 创建任务包装器
        async def task_wrapper():
            timeout = getattr(task.rule_config, "timeout", 60)  # 默认超时 60 秒
            error_occurred = False

            try:
                # 使用超时机制执行任务
                try:
                    # 在测试中，我们使用模拟的异步生成器，它们需要特殊处理
                    # 不使用 wait_for 直接包装异步生成器，而是使用单独的超时检查
                    start_time = time.time()

                    # 注意：执行协程已经注册到输出管理器，这里不需要手动迭代
                    # 只需要等待协程完成或超时
                    while True:
                        # 检查任务是否已经完成
                        if task.is_completed():
                            logger.debug(
                                f"Task {task.task_id} is already completed, exiting wrapper"
                            )
                            break

                        # 检查是否超时
                        if time.time() - start_time > timeout:
                            raise asyncio.TimeoutError(
                                f"Task execution timed out after {timeout} seconds"
                            )

                        # 更新最后活动时间
                        self._task_last_activity[task.task_id] = time.time()

                        # 短暂等待后继续检查
                        await asyncio.sleep(0.1)

                except asyncio.TimeoutError:
                    error_occurred = True
                    logger.error(
                        f"Task {task.task_id} timed out after {timeout} seconds"
                    )

                    # 创建一个错误消息生成器并注册到输出管理器
                    async def error_generator():
                        yield f"Error: Task execution timed out after {timeout} seconds"

                    # 注册错误消息生成器
                    await self._output_manager.register_stream(
                        error_generator(), metadata
                    )
                    # 直接设置任务状态为失败
                    task._state = TaskState.FAILED
                    task._success = False
                    logger.debug(
                        f"Task {task.task_id} state changed: {TaskState.EXECUTING.value} -> {TaskState.FAILED.value}"
                    )
            except Exception as e:
                error_occurred = True
                logger.error(f"Error executing task {task.task_id}: {e}", exc_info=True)
                try:
                    # 直接设置任务状态为失败，避免使用异步方法
                    task._state = TaskState.FAILED
                    task._success = False
                    logger.debug(
                        f"Task {task.task_id} state changed: {TaskState.EXECUTING.value} -> {TaskState.FAILED.value}"
                    )
                except Exception as state_error:
                    logger.error(f"Error setting task state to FAILED: {state_error}")
            finally:
                # 释放信号量
                self._task_semaphore.release()

                # 确保任务状态一致
                if not task.is_completed():
                    try:
                        # 如果任务还没有被标记为完成，则设置其状态
                        if error_occurred:
                            # 直接设置任务状态为失败，避免使用异步方法
                            task._state = TaskState.FAILED
                            task._success = False
                            logger.debug(
                                f"Task {task.task_id} state changed: {TaskState.EXECUTING.value} -> {TaskState.FAILED.value}"
                            )
                        else:
                            # 直接设置任务状态为完成，避免使用异步方法
                            task._state = TaskState.COMPLETED
                            task._success = True
                            logger.debug(
                                f"Task {task.task_id} state changed: {TaskState.EXECUTING.value} -> {TaskState.COMPLETED.value}"
                            )
                    except Exception as state_error:
                        logger.error(f"Error setting final task state: {state_error}")

        # 创建并跟踪异步任务
        scheduled_async_task = asyncio.create_task(task_wrapper())
        self._active_task_executions.add(scheduled_async_task)
        scheduled_async_task.add_done_callback(
            self._active_task_executions.discard
        )  # 完成时自动移除

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """
        提供最终输出的异步生成器。
        使用OutputStreamManager管理多个输出流，
        当所有任务完成且所有输出流耗尽时结束。
        """
        # 启动监控循环作为后台任务
        monitor_task = asyncio.create_task(self._monitor_tasks_completion())

        try:
            # 持续检查是否有任务正在执行或等待调度
            while True:
                # 检查是否有输出可用
                has_output = False
                async for chunk in self._output_manager.get_output_stream():
                    has_output = True
                    yield chunk

                # 检查是否所有任务都已完成
                active_tasks = [
                    task for task in self._tasks.values() if not task.is_completed()
                ]
                active_executions = len(self._active_task_executions)
                pending_in_queue = len(self._task_priority_queue)

                # 如果没有活动任务、执行中的任务和待处理任务，并且没有输出，则结束
                if (
                    not active_tasks
                    and active_executions == 0
                    and pending_in_queue == 0
                    and not has_output
                ):
                    logger.debug("所有任务已完成且输出流已耗尽，结束输出流")
                    break

                # 短暂等待后再次检查
                await asyncio.sleep(0.1)
        finally:
            # 取消监控任务
            if not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    async def _monitor_tasks_completion(self) -> None:
        """监控任务完成情况，确保所有任务都能被正确处理"""
        try:
            while True:
                # 检查是否有任务需要调度但尚未调度
                if len(self._task_priority_queue) > 0:
                    rule_id = self._task_priority_queue.get()
                    if rule_id:
                        await self._check_and_create_task_if_needed(rule_id)

                # 短暂等待后继续检查
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug("任务完成监控被取消")
            raise
        except Exception as e:
            logger.error(f"任务完成监控出错: {e}")

    async def _monitor_loop(self) -> None:
        """监控循环，检查任务状态和潜在的死锁"""
        last_progress_time = time.time()
        last_deadlock_check_time = time.time()

        while True:
            await asyncio.sleep(1)  # 每秒检查一次

            current_time = time.time()

            # 检查是否有新的输出
            # 输出流管理器会自动管理输出流
            last_progress_time = current_time

            # 检查死锁情况 - 每 5 秒检查一次
            if current_time - last_deadlock_check_time > 5:
                # 检查长时间没有进展的任务
                for task_id, last_activity_time in list(
                    self._task_last_activity.items()
                ):
                    if (
                        task_id in self._tasks
                        and not self._tasks[task_id].is_completed()
                    ):
                        # 检查任务是否长时间没有活动
                        if (
                            current_time - last_activity_time
                            > self._deadlock_detection_time
                        ):
                            logger.warning(
                                f"Task {task_id} has been inactive for {self._deadlock_detection_time} seconds. Possible deadlock."
                            )
                            # 可以在这里实现恢复策略，例如强制完成或重试任务
                            try:
                                # 尝试将长时间无活动的任务标记为失败
                                if self._tasks[task_id].is_executing():
                                    await self._tasks[task_id].set_state(
                                        TaskState.FAILED
                                    )
                                    logger.warning(
                                        f"Marked stuck task {task_id} as FAILED"
                                    )
                            except Exception as e:
                                logger.error(
                                    f"Error handling stuck task {task_id}: {e}"
                                )

                # 检查整体进展 - 更精细的流活动检测
                inactive_streams = []
                for stream_id, stream_data in self._output_manager._streams.items():
                    if not stream_data.get("exhausted", False):
                        metadata = stream_data.get("metadata")
                        if metadata and hasattr(metadata, "last_activity_at"):
                            stream_inactive_time = (
                                current_time - metadata.last_activity_at.timestamp()
                            )
                            if stream_inactive_time > self._deadlock_detection_time:
                                inactive_streams.append(
                                    (stream_id, metadata.task_id, stream_inactive_time)
                                )

                if inactive_streams and self._active_task_executions:
                    # 有长时间不活跃的流和活动任务
                    for stream_id, task_id, inactive_time in inactive_streams:
                        logger.warning(
                            f"Stream {stream_id} for task {task_id} has been inactive for {inactive_time:.1f} seconds. Possible deadlock."
                        )

                    # 可以在这里实现针对特定流的恢复策略
                    logger.warning(
                        f"Potential deadlock detected. {len(inactive_streams)} streams have no progress for over {self._deadlock_detection_time} seconds"
                    )
                    # 可以在这里实现恢复策略

                # 更新最后检查时间
                last_deadlock_check_time = current_time

    async def shutdown(self) -> None:
        """关闭调度器并清理资源"""
        logger.info("Shutting down RuleDispatcher...")

        # 取消所有活动任务
        cancel_tasks = []
        for task_execution in list(self._active_task_executions):
            if not task_execution.done():
                task_execution.cancel()
                cancel_tasks.append(task_execution)

        # 等待所有任务完成或取消
        if cancel_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cancel_tasks, return_exceptions=True), timeout=2.0
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout waiting for tasks to cancel. Some tasks may still be running."
                )

        # 清理资源
        self._active_task_executions.clear()
        logger.info("All active task executions cancelled or finished.")

        # 将所有未完成的任务标记为失败
        state_change_tasks = []
        failed_task_ids = []

        for task_id, task in self._tasks.items():
            if not task.is_completed():
                try:
                    # 创建任务并收集引用，以便等待完成
                    state_change_task = asyncio.create_task(
                        task.set_state(TaskState.FAILED)
                    )
                    state_change_tasks.append(state_change_task)
                    failed_task_ids.append(task_id)
                except Exception as e:
                    logger.error(f"Failed to set task {task_id} state to FAILED: {e}")

        # 等待所有状态变更完成
        if state_change_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*state_change_tasks, return_exceptions=True),
                    timeout=1.0,
                )
                for task_id in failed_task_ids:
                    logger.debug(
                        f"Marked incomplete task {task_id} as FAILED during shutdown"
                    )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout waiting for task state changes. Some tasks may not be properly marked as failed."
                )
            except Exception as e:
                logger.error(f"Error during task state changes: {e}")

        # 清理输出流管理器
        if hasattr(self, "_output_manager"):
            try:
                # 关闭所有流
                for stream_id in list(self._output_manager._streams.keys()):
                    self._output_manager.unregister_stream(stream_id)
            except Exception as e:
                logger.error(f"Error cleaning up output stream manager: {e}")

        logger.info("RuleDispatcher shutdown complete.")

        # 输出流管理器会在其内部自动清理资源

        # 清理其他资源
        self._rule_priorities.clear()
        self._task_last_activity.clear()

        logger.info("RuleDispatcher shut down.")

        # 取消事件总线订阅
        try:
            self._event_bus.unsubscribe("ctx_changed", self._handle_ctx_changed)
            logger.debug("Unsubscribed from ctx_changed event")
        except Exception as e:
            logger.error(f"Error unsubscribing from events: {e}")
