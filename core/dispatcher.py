import asyncio
import logging
import uuid
from typing import List, Dict, Set, Any, AsyncGenerator

from core.rule_config import RuleConfig

from core.event_bus import EventBus
from core.observable_ctx import ObservableCtx
from core.rule_task import RuleTask


logger = logging.getLogger(__name__)


class RuleDispatcher:

    def __init__(
        self, initial_rules: List[RuleConfig], event_bus: EventBus, ctx: ObservableCtx
    ):
        self._event_bus = event_bus
        self._ctx = ctx

        # 通过ID存储所有任务
        self._tasks: Dict[str, RuleTask] = {}
        # 跟踪正在运行的asyncio任务
        self._active_task_executions: Set[asyncio.Task] = set()
        # 用于DIRECT_RETURN输出
        self._output_queue: asyncio.Queue[str] = (
            asyncio.Queue()
        )  # 用于DIRECT_RETURN输出

        # 订阅ctx_changed事件
        self._event_bus.subscribe(
            event_type="ctx_changed", callback=self._handle_ctx_changed
        )
        # 添加初始规则
        for rule_config in initial_rules:
            self.add_new_rule(rule_config)

    def _generate_task_id(self) -> str:
        return str(uuid.uuid4())

    def add_new_rule(self, rule_config: RuleConfig, immediate: bool = False) -> str:
        task_id = self._generate_task_id()
        task = RuleTask(rule_config, task_id)
        self._tasks[task_id] = task
        logger.info(
            f"Added new rule task:\n {task_id} (Name: {rule_config.name if hasattr(rule_config, 'name') else 'N/A'}, Depend_ctx_key: {rule_config.depend_ctx_key}, Condition: {rule_config.match_condition})"
        )
        # 立即检查这个新规则是否可以调度
        if immediate:
            self._check_and_schedule_task_if_needed(task)
        return task_id

    async def _handle_ctx_changed(self, event_data: Dict[str, Any]) -> None:
        changed_key = event_data.get("key")
        changed_value = self._ctx.get(changed_key)
        logger.debug(
            f"Ctx changed: key='{changed_key}', changed value: {changed_value}"
        )
        for task in self._tasks.values():
            if task.is_completed() or task.is_executing():
                # 只检查尚未完成或正在处理的任务
                continue
            if (
                task.rule_config.depend_ctx_key is not None
                and changed_key in task.rule_config.depend_ctx_key
            ):
                logger.debug(
                    f"Task {task.task_id} depends on {changed_key}. Evaluating."
                )
                self._check_and_schedule_task_if_needed(task)
            else:
                logger.debug(
                    f"Task {task.task_id} does not depend on {changed_key}. Skipping."
                )

    def _check_and_schedule_task_if_needed(self, task: RuleTask) -> None:
        # 检查任务是否已经在执行中（避免重复调度）
        if task.is_executing():
            logger.debug(
                f"Task {task.task_id} is already executing. Skipping scheduling."
            )
            return

        if not task.is_condition_meet(self._ctx):
            logger.debug(
                f"Task {task.task_id} is not meet the condition. Skipping scheduling."
            )
            return

        logger.debug(
            f"Task {task.task_id} (Name: {task.rule_config.name if hasattr(task.rule_config, 'name') else 'N/A'}) is ready. Scheduling for execution."
        )
        task.set_executing(True)  # 标记为执行中

        execution_coro = task.execute_tool(ctx=self._ctx, dispatcher=self)

        async def task_wrapper():
            try:
                async for output_chunk in execution_coro:
                    await self._output_queue.put(output_chunk)
            except Exception as e:
                logger.error(f"Error executing task {task.task_id}: {e}", exc_info=True)
                task.set_completed(True, success=False)  # 标记为完成但失败
            finally:
                if (
                    not task.is_completed()
                ):  # 确保如果execute没有明确标记完成，则标记为完成
                    task.set_completed(True, success=True)  # 如果没有异常则假设成功
                task.set_executing(False)  # 取消执行中标记
                # 检查其他任务是否因为此任务完成而变为就绪状态（例如，如果一个规则依赖于另一个规则的完成信号）
                # 目前，ctx_changed事件是重新评估的主要触发器。

        scheduled_async_task = asyncio.create_task(task_wrapper())
        self._active_task_executions.add(scheduled_async_task)
        scheduled_async_task.add_done_callback(
            self._active_task_executions.discard
        )  # 完成时自动移除

    async def dispatch_initial(self) -> None:
        """
        初始化时调用一次，设置初始用户输入并触发初始规则检查。
        """
        # TODO
        pass

    async def get_output_stream(self) -> AsyncGenerator[str, None]:
        """
        提供最终输出的异步生成器。
        当没有任务正在运行，输出队列为空，
        且当前上下文下没有待处理的任务可以就绪时结束。
        """
        while True:
            # 首先尝试从输出队列获取项目
            try:
                chunk = await asyncio.wait_for(self._output_queue.get(), timeout=0.05)
                yield chunk
                continue  # 成功获取到块，继续循环
            except asyncio.TimeoutError:
                # 在指定时间内输出队列为空或没有新的 chunk 到达
                # 现在检查是否应该结束
                pass  # 继续检查下面的结束条件
            except asyncio.CancelledError:
                logger.debug("Output stream cancelled.")
                break

            # 输出队列超时时检查结束条件：
            # 条件1：当前是否有正在运行的 asyncio Task（规则执行包装器）？
            if self._active_task_executions:
                # 有活动任务，等待它们完成或上下文改变
                logger.debug(
                    "get_output_stream: Active tasks exist. Waiting for them to complete or context to change."
                )
                await asyncio.sleep(0.5)  # 让出控制权给事件循环
                continue

            # 条件2：没有活动的asyncio Task。是否有就绪的RuleTask？
            # RuleTask如果未完成且满足条件则为就绪状态
            any_task_is_runnable = any(
                not task.is_completed() and task.is_condition_meet(self._ctx)
                for task in self._tasks.values()
            )

            if any_task_is_runnable:
                # 有就绪的任务但可能尚未被调度器选中
                # （例如：上下文改变事件刚刚发生）
                # 等待事件循环处理
                logger.debug(
                    "get_output_stream: No active executions, but a task is ready. Yielding briefly."
                )
                await asyncio.sleep(0.5)
                continue

            # 条件3：没有活动的asyncio Task，输出队列为空（发生超时），
            # 且当前上下文下没有可运行的RuleTask
            # 这意味着所有任务都已完成，或者剩余任务在当前状态下无法继续
            logger.debug(
                "No active executions, output queue was empty, and no task is currently runnable. Ending stream."
            )
            break

    async def shutdown(self) -> None:
        logger.info("Shutting down RuleDispatcher...")
        for task_execution in list(self._active_task_executions):  # 遍历副本
            if not task_execution.done():
                task_execution.cancel()

        if self._active_task_executions:
            await asyncio.gather(*self._active_task_executions, return_exceptions=True)

        self._active_task_executions.clear()
        logger.info("All active task executions cancelled or finished.")
        # 清空输出队列
        while not self._output_queue.empty():
            self._output_queue.get_nowait()
            self._output_queue.task_done()  # 如果使用task_done/join
        logger.info("RuleDispatcher shut down.")
