import asyncio
import uuid
import logging
from typing import Dict, Any, AsyncGenerator
from datetime import datetime
from pydantic import BaseModel, Field

from core.event_bus import EventBus
from core.event_types import EventType, ChangeType

logger = logging.getLogger(__name__)


class StreamMetadata(BaseModel):
    """流元数据，描述一个输出流的属性"""

    rule_name: str
    rule_id: str
    task_id: str
    rule_priority: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity_at: datetime = Field(default_factory=datetime.now)
    status: str = "active"  # 可能的状态: active, exhausted, error, cancelled

    def model_dump(self) -> Dict[str, Any]:
        """返回可序列化的字典表示，将datetime转换为字符串"""
        data = super().model_dump()
        # 将datetime对象转换为ISO格式字符串
        if "created_at" in data and isinstance(data["created_at"], datetime):
            data["created_at"] = data["created_at"].isoformat()
        if "last_activity_at" in data and isinstance(
            data["last_activity_at"], datetime
        ):
            data["last_activity_at"] = data["last_activity_at"].isoformat()
        return data


class OutputChunk:
    """单个输出块，包含内容和对应的元数据引用"""

    def __init__(self, content: str, metadata_ref: StreamMetadata):
        self.content = content
        self.metadata = metadata_ref

    def dict(self) -> Dict[str, Any]:
        """返回可序列化的字典表示"""
        return {"content": self.content, "metadata": self.metadata.model_dump()}


class OutputStreamManager:
    """输出流管理器，负责管理和合并多个异步生成器的输出"""

    def __init__(self, event_bus: EventBus):
        """初始化输出流管理器"""
        self._streams: Dict[str, Dict[str, Any]] = (
            {}
        )  # stream_id -> {generator, metadata, exhausted}
        self._lock = asyncio.Lock()  # 用于保护流注册和注销的锁
        self._event_bus = event_bus
        if self._event_bus:
            self._event_bus.subscribe(EventType.TASK_CHANGED, self._handle_task_event)

    async def _handle_task_event(self, event_data: Dict[str, Any]):
        """处理任务状态变更事件"""
        # 只关注任务完成或失败事件
        if event_data["change_type"] not in [
            ChangeType.TASK_COMPLETED,
            ChangeType.TASK_FAILED,
        ]:
            return

        task_id = event_data["task_id"]

        # 查找与该任务关联的所有流
        task_streams = []
        async with self._lock:
            for stream_id, stream_data in self._streams.items():
                if stream_data["metadata"].task_id == task_id:
                    task_streams.append((stream_id, stream_data))

        # 检查每个流的状态，如果已耗尽则注销
        for stream_id, stream_data in task_streams:
            if stream_data.get("exhausted", False):
                await self.unregister_stream(stream_id)
                logger.info(
                    f"Stream {stream_id} for task {task_id} unregistered after task completion"
                )

    async def register_stream(self, generator, metadata: StreamMetadata) -> str:
        """
        注册一个新的输出流

        Args:
            generator: 异步生成器
            metadata: 流元数据

        Returns:
            stream_id: 流ID
        """
        async with self._lock:
            stream_id = str(uuid.uuid4())
            self._streams[stream_id] = {
                "generator": generator,
                "metadata": metadata,
                "exhausted": False,
            }
            logger.debug(f"Registered stream {stream_id} for task {metadata.task_id}")
            return stream_id

    async def unregister_stream(self, stream_id: str) -> None:
        """
        注销一个输出流

        Args:
            stream_id: 流ID
        """
        async with self._lock:
            if stream_id in self._streams:
                logger.info(f"Unregistered stream {stream_id}")
                self._streams.pop(stream_id)
            else:
                logger.warning(
                    f"Attempted to unregister non-existent stream {stream_id}"
                )

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """
        按注册顺序获取所有输出流

        使用异步迭代器模式，按注册顺序遍历所有流
        当所有流都耗尽时自动结束
        """
        # 创建一个流ID列表的副本，用于按注册顺序处理流
        stream_ids = list(self._streams.keys())

        # 记录已耗尽的流
        exhausted_streams = set()

        # 当还有未耗尽的流时继续循环
        while len(exhausted_streams) < len(stream_ids):
            # 遍历所有流
            for stream_id in stream_ids:
                # 如果流已耗尽，跳过
                if stream_id in exhausted_streams or stream_id not in self._streams:
                    continue

                # 获取生成器和元数据
                stream_data = self._streams[stream_id]
                generator = stream_data["generator"]
                metadata = stream_data["metadata"]

                try:
                    # 尝试获取下一个数据块
                    content = await generator.__anext__()

                    # 更新流的最后活动时间
                    self._streams[stream_id][
                        "metadata"
                    ].last_activity_at = datetime.now()

                    # 创建输出块并产生
                    chunk = OutputChunk(content=content, metadata_ref=metadata)
                    yield chunk

                except StopAsyncIteration:
                    # 生成器已耗尽，标记为已完成
                    logger.info(f"Stream {stream_id} exhausted")
                    exhausted_streams.add(stream_id)
                    self.make_stream_exhausted(stream_id)

                except asyncio.CancelledError:
                    # 处理取消操作
                    logger.warning(f"Stream {stream_id} was cancelled")
                    exhausted_streams.add(stream_id)
                    self.make_stream_exhausted(stream_id)
                    # 在取消时不抛出异常，而是正常结束流

                except Exception as e:
                    # 其他错误，标记为已完成并记录错误
                    logger.error(f"Error getting data from stream {stream_id}: {e}")
                    # 尝试产生错误消息
                    try:
                        error_chunk = OutputChunk(
                            content=f"Error: {str(e)}", metadata_ref=metadata
                        )
                        yield error_chunk

                    except Exception as yield_error:
                        logger.error(
                            f"Failed to yield error message or update task state: {yield_error}"
                        )
                    exhausted_streams.add(stream_id)
                    self.make_stream_exhausted(stream_id)

            # 如果还有未耗尽的流，短暂等待后继续
            if len(exhausted_streams) < len(stream_ids):
                await asyncio.sleep(0.01)

        logger.debug("All streams exhausted. Ending output stream.")

        # 清理已耗尽的流
        async with self._lock:
            for stream_id in exhausted_streams:
                if stream_id in self._streams:
                    self._streams[stream_id]["exhausted"] = True

    async def make_stream_exhausted(self, stream_id):
        # 标记流为已耗尽
        self._streams[stream_id]["exhausted"] = True
        # 更新流状态和最后活动时间
        if stream_id in self._streams:
            self._streams[stream_id]["metadata"].status = "exhausted"
            self._streams[stream_id]["metadata"].last_activity_at = datetime.now()
        # 发布流耗尽事件
        if self._event_bus:
            metadata: StreamMetadata = self._streams[stream_id]["metadata"]
            await self._event_bus.publish(
                EventType.STREAM_CHANGED,
                change_type=ChangeType.STREAM_EXHAUSTED,
                stream_id=stream_id,
                task_id=metadata.task_id,
                rule_id=metadata.rule_id,
                last_activity_at=metadata.last_activity_at.isoformat(),
                status=metadata.status,
            )
