import asyncio
import uuid
import logging
from typing import Dict, Any, AsyncGenerator
from datetime import datetime

from core.task_state import TaskInfo


class OutputChunk:
    """单个输出块，包含内容和对应的元数据引用"""

    def __init__(self, content: str, task_info: TaskInfo):
        self.content = content
        self.task_info = task_info

    def dict(self) -> Dict[str, Any]:
        """返回可序列化的字典表示"""
        return {"content": self.content, "task_info": self.task_info.to_dict()}


class OutputStreamManager:
    """输出流管理器，负责管理和合并多个异步生成器的输出"""

    def __init__(self, logger: logging.Logger):
        """初始化输出流管理器"""
        self._logger: logging.Logger = logger
        self._register_stream = asyncio.Queue()  # {generator, task_info, exhausted}
        self._registered_cnt = 0

    def register_stream(
        self, async_generator: AsyncGenerator[str, None], task_info: TaskInfo
    ) -> str:
        """
        注册一个新的输出流

        Args:
            async_generator: 异步生成器
            task_info: 任务信息

        Returns:
            stream_id: 流ID
        """
        stream_id = str(uuid.uuid4())
        self._registered_cnt += 1
        self._register_stream.put_nowait(
            {
                "stream_id": stream_id,
                "generator": async_generator,
                "task_info": task_info,
                "exhausted": False,
            }
        )
        self._logger.info(f"Registered stream {stream_id} for task {task_info.task_id}")

        return stream_id

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """
        按注册顺序获取所有输出流

        使用异步迭代器模式，按注册顺序遍历所有流
        当所有流都耗尽时自动结束
        """
        # 记录已耗尽的流
        exhausted_streams = set()
        # 总等待时间，用于超时控制
        total_wait_time = 0
        # 单次等待时间
        wait_time = 0
        # 最大等待时间（秒）
        max_wait_time = 5
        # 是否有活动
        had_activity = False

        while True:
            # 终止条件1：所有已注册的流都已耗尽
            if self._registered_cnt > 0 and len(exhausted_streams) >= self._registered_cnt:
                self._logger.info(f"所有注册的流 ({self._registered_cnt}) 已耗尽，结束输出流")
                break
            else:
                self._logger.info(f"等待流耗尽，已耗尽 {len(exhausted_streams)} 个流")
                
            # 终止条件2：长时间没有新的流注册且没有活动
            if total_wait_time > max_wait_time and not had_activity:
                self._logger.warning(f"超过 {max_wait_time} 秒没有新的流注册或活动，结束输出流")
                break
            else:
                self._logger.info(f"等待流注册，已等待 {total_wait_time:.1f} 秒")
            # 如果没有注册的流，等待一段时间
            if self._registered_cnt == 0:
                await asyncio.sleep(0.2)
                wait_time += 0.2
                total_wait_time += 0.2
                
                if wait_time >= 1:  # 每秒记录一次日志
                    self._logger.info(f"等待流注册，已等待 {total_wait_time:.1f} 秒")
                    wait_time = 0
                    
                if total_wait_time > 5:
                    self._logger.warning("等待超过 5 秒没有流注册，结束输出流")
                    break
                continue
            else:
                self._logger.info(f"流注册 {self._registered_cnt}，已等待 {total_wait_time:.1f} 秒")
                
            # 有活动时重置总等待时间
            if had_activity:
                total_wait_time = 0
                had_activity = False
                self._logger.info(f"流活动 {self._registered_cnt}，已等待 {total_wait_time:.1f} 秒, reset")
            else:
                self._logger.info(f"流活动 {self._registered_cnt}，已等待 {total_wait_time:.1f} 秒")
                
            try:
                # 非阻塞方式获取流数据
                stream_data = self._register_stream.get_nowait()
                if stream_data is None or stream_data["exhausted"]:
                    self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
                    continue
                    
                generator = stream_data["generator"]
                self._logger.info(f"消费流 {stream_data['stream_id']} (任务: {stream_data['task_info'].task_id})")
                
                if generator is None:
                    self._logger.error(f"生成器为空，任务: {stream_data['task_info'].task_id}")
                    # 标记流为已耗尽
                    exhausted_streams.add(stream_data["stream_id"])
                    stream_data["exhausted"] = True
                    self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
                    continue
                    
                task_info = stream_data["task_info"]
                content_yielded = False
                
                # 处理生成器内容
                try:
                    async for content in generator:
                        # 更新流的最后活动时间
                        task_info.update_at = datetime.now()
                        # 创建输出块并产生
                        chunk = OutputChunk(content=content, task_info=task_info)
                        yield chunk
                        had_activity = True
                        content_yielded = True
                        
                except StopAsyncIteration:
                    # 生成器已耗尽，标记为已完成
                    self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
                    
                # 标记流为已耗尽
                exhausted_streams.add(stream_data["stream_id"])
                stream_data["exhausted"] = True
                
                # 如果有内容产生，表示有活动
                if content_yielded:
                    had_activity = True
                    
            except asyncio.QueueEmpty:
                # 队列为空，等待一段时间
                await asyncio.sleep(0.2)
                wait_time += 0.2
                total_wait_time += 0.2
                
                if wait_time >= 1:  # 每秒记录一次日志
                    remaining = self._registered_cnt - len(exhausted_streams)
                    if remaining > 0:
                        self._logger.info(f"等待 {remaining} 个流完成，已等待 {total_wait_time:.1f} 秒")
                    wait_time = 0
                continue
                
            except Exception as e:
                # 其他错误处理
                self._logger.error(f"处理流时发生错误: {e}")
                try:
                    # 尝试产生错误消息
                    error_chunk = OutputChunk(
                        content=f"Error: {str(e)}", task_info=task_info
                    )
                    yield error_chunk
                    had_activity = True
                except Exception as yield_error:
                    self._logger.error(f"无法产生错误消息: {yield_error}")
                    
                # 标记流为已耗尽
                exhausted_streams.add(stream_data["stream_id"])
                stream_data["exhausted"] = True
                self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")

        self._logger.info("All streams exhausted. Ending output stream.")
