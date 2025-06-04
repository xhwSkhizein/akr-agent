import asyncio
import uuid
import logging
from typing import Dict, Any, AsyncGenerator
from datetime import datetime

from .task_state import TaskInfo


class OutputChunk:
    """单个输出块，包含内容和对应的元数据引用"""

    def __init__(self, content: str, task_info: TaskInfo):
        self.content = content
        self.task_info = task_info

    def dict(self) -> Dict[str, Any]:
        """返回可序列化的字典表示"""
        return {"content": self.content, "task_info": self.task_info.to_dict()}

class OutputStreamManager:
    """输出流管理器，负责管理和按顺序处理多个异步生成器的输出"""

    def __init__(self, logger: logging.Logger, stream_registration_timeout: float = 5.0):
        """
        初始化输出流管理器
        Args:
            logger: 日志记录器
            stream_registration_timeout: 当所有已知流处理完毕后，等待新流注册的超时时间（秒）
        """
        self._logger: logging.Logger = logger
        # _stream_queue stores dictionaries:
        # {"stream_id": str, "generator": AsyncGenerator, "task_info": TaskInfo}
        self._stream_queue = asyncio.Queue()
        self._stream_registration_timeout = stream_registration_timeout
        self._registered_stream_count = 0 # Total number of streams ever registered
        self._streams_processed_count = 0
        self._stream_exhausted = False

    def register_stream(
        self, async_generator: AsyncGenerator[str, None], task_info: TaskInfo
    ) -> str:
        """
        注册一个新的输出流。流将按注册顺序被处理。

        Args:
            async_generator: 异步生成器
            task_info: 任务信息

        Returns:
            stream_id: 流ID
        """
        stream_id = str(uuid.uuid4())
        # Increment count *before* putting, to signal intent if get_output_stream is checking.
        self._registered_stream_count += 1
        self._stream_queue.put_nowait(
            {
                "stream_id": stream_id,
                "generator": async_generator,
                "task_info": task_info,
            }
        )
        self._logger.info(
            f"Registered stream {stream_id} for task {task_info.task_id}. "
            f"Queue size: {self._stream_queue.qsize()}, Total registered: {self._registered_stream_count}"
        )
        self._stream_exhausted = False
        return stream_id

    async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
        """
        按注册顺序获取并处理所有输出流的内容。

        此方法会按顺序从队列中取出每个已注册的流，并完整地消耗该流的
        所有输出，然后才处理下一个流。当所有已注册的流都处理完毕，
        并且在一定的超时时间内没有新的流注册时，此异步生成器结束。
        """
        if self._stream_exhausted:
            self._logger.info("Output stream already exhausted, returning empty generator.")
            return

        while True:
            stream_data: Dict[str, Any] = {} # Ensure it's defined for 'finally' if an early error occurs
            current_stream_id: str = "N/A"

            try:
                if self._streams_processed_count >= self._registered_stream_count:
                    # All streams registered *up to this point* have been processed.
                    # Now, wait for a *new* stream registration with a timeout.
                    self._logger.info(
                        f"All {self._streams_processed_count}/{self._registered_stream_count} known streams processed. "
                        f"Waiting for new stream registrations with timeout ({self._stream_registration_timeout}s)..."
                    )
                    try:
                        stream_data = await asyncio.wait_for(
                            self._stream_queue.get(), timeout=self._stream_registration_timeout
                        )
                        # If we get here, a new stream was registered and added.
                        # _registered_stream_count would have been incremented by register_stream.
                    except asyncio.TimeoutError:
                        self._logger.info(
                            f"Timeout waiting for new stream registrations. "
                            f"Total processed: {self._streams_processed_count}. No new streams detected. Ending output."
                        )
                        break # Exit the main `while True` loop
                    except asyncio.CancelledError:
                        self._logger.info("Output stream task cancelled while waiting for new stream.")
                        break
                else:
                    # We expect more streams based on _registered_stream_count.
                    # Wait (potentially indefinitely if tasks keep registering) for the next one.
                    self._logger.info(
                        f"Waiting for next stream. Processed: {self._streams_processed_count}/{self._registered_stream_count}. "
                        f"Queue size: {self._stream_queue.qsize()}."
                    )
                    try:
                        stream_data = await self._stream_queue.get()
                    except asyncio.CancelledError:
                        self._logger.info("Output stream task cancelled while waiting for stream.")
                        break
                
                # Deconstruct stream data safely
                generator = stream_data.get("generator")
                task_info = stream_data.get("task_info")
                current_stream_id = stream_data.get("stream_id", "UnknownStreamID")

                if not generator or not task_info: # Basic validation
                    self._logger.error(f"Stream {current_stream_id} received with invalid data (missing generator or task_info). Skipping.")
                    # This stream is considered "processed" to advance past it.
                else:
                    self._logger.info(f"Processing stream {current_stream_id} for task {task_info.task_id}")
                    try:
                        async for content in generator:
                            task_info.update_at = datetime.now() # Update timestamp on activity
                            chunk = OutputChunk(content=content, task_info=task_info)
                            yield chunk
                        self._logger.info(f"Stream {current_stream_id} (Task: {task_info.task_id}) exhausted normally.")
                    except Exception as e:
                        self._logger.error(f"Error processing stream {current_stream_id} (Task: {task_info.task_id}): {e}", exc_info=False) # Set exc_info=True for full traceback
                        if task_info: # Ensure task_info is available to create an error chunk
                            try:
                                error_chunk = OutputChunk(
                                    content=f"Error in stream {current_stream_id}: {str(e)}",
                                    task_info=task_info
                                )
                                yield error_chunk
                            except Exception as yield_error:
                                self._logger.error(f"Failed to yield error chunk for stream {current_stream_id}: {yield_error}")
                        # Stream processing ends here due to error.
            
            except asyncio.CancelledError:
                self._logger.info(f"Output stream task cancelled during processing cycle (around stream {current_stream_id}).")
                break
            except Exception as e: # Catch unexpected errors in the manager's loop logic itself
                self._logger.error(f"Unexpected error in get_output_stream main loop (around stream {current_stream_id}): {e}", exc_info=True)
                break # Critical error in manager logic, safer to stop.
            finally:
                # This block ensures that for every item attempted to be processed (even if it failed or was invalid),
                # we mark it as "done" with the queue and increment our processed counter.
                if stream_data: # stream_data would be populated if .get() succeeded
                    self._stream_queue.task_done()
                    self._streams_processed_count += 1
                # self._logger.debug(f"Incremented processed_streams_count to {self._streams_processed_count} after handling item associated with {current_stream_id}.")

        self._logger.info(
            f"Output stream finished. Total streams processed: {self._streams_processed_count}. "
            f"Final registered count: {self._registered_stream_count}."
        )
        self._stream_exhausted = True
# class OutputStreamManager:
#     """输出流管理器，负责管理和合并多个异步生成器的输出"""

#     def __init__(self, logger: logging.Logger):
#         """初始化输出流管理器"""
#         self._logger: logging.Logger = logger
#         self._register_stream = asyncio.Queue()  # {generator, task_info, exhausted}
#         self._registered_cnt = 0

#     def register_stream(
#         self, async_generator: AsyncGenerator[str, None], task_info: TaskInfo
#     ) -> str:
#         """
#         注册一个新的输出流

#         Args:
#             async_generator: 异步生成器
#             task_info: 任务信息

#         Returns:
#             stream_id: 流ID
#         """
#         stream_id = str(uuid.uuid4())
#         self._registered_cnt += 1
#         self._register_stream.put_nowait(
#             {
#                 "stream_id": stream_id,
#                 "generator": async_generator,
#                 "task_info": task_info,
#                 "exhausted": False,
#             }
#         )
#         self._logger.info(f"Registered stream {stream_id} for task {task_info.task_id}")

#         return stream_id

#     async def get_output_stream(self) -> AsyncGenerator[OutputChunk, None]:
#         """
#         按注册顺序获取所有输出流

#         使用异步迭代器模式，按注册顺序遍历所有流
#         当所有流都耗尽时自动结束
#         """
#         # 记录已耗尽的流
#         exhausted_streams = set()
#         # 总等待时间，用于超时控制
#         total_wait_time = 0
#         # 单次等待时间
#         wait_time = 0
#         # 最大等待时间（秒）
#         max_wait_time = 5
#         # 是否有活动
#         had_activity = False

#         while True:
#             # 终止条件1：所有已注册的流都已耗尽
#             if self._registered_cnt > 0 and len(exhausted_streams) >= self._registered_cnt:
#                 self._logger.info(f"所有注册的流 ({self._registered_cnt}/{len(exhausted_streams)}) 已耗尽，结束输出流")
#                 break
#             else:
#                 self._logger.info(f"等待流耗尽，已耗尽 {len(exhausted_streams)/self._registered_cnt} 个流")
                
#             # 终止条件2：长时间没有新的流注册且没有活动
#             if total_wait_time > max_wait_time and not had_activity:
#                 self._logger.warning(f"超过 {max_wait_time} 秒没有新的流注册或活动，结束输出流")
#                 break
#             else:
#                 self._logger.info(f"等待流注册，已等待 {total_wait_time:.1f} 秒")
#             # 如果没有注册的流，等待一段时间
#             if self._registered_cnt == 0:
#                 await asyncio.sleep(0.2)
#                 wait_time += 0.2
#                 total_wait_time += 0.2
                
#                 if wait_time >= 1:  # 每秒记录一次日志
#                     self._logger.info(f"等待流注册，已等待 {total_wait_time:.1f} 秒")
#                     wait_time = 0
                    
#                 if total_wait_time > 5:
#                     self._logger.warning("等待超过 5 秒没有流注册，结束输出流")
#                     break
#                 continue
#             else:
#                 self._logger.info(f"流注册/完成= {self._registered_cnt/len(exhausted_streams)}，已等待 {total_wait_time:.1f} 秒")
                
#             # 有活动时重置总等待时间
#             if had_activity:
#                 total_wait_time = 0
#                 had_activity = False
#                 self._logger.info(f"流活动 {self._registered_cnt/len(exhausted_streams)}，已等待 {total_wait_time:.1f} 秒, reset")
#             else:
#                 self._logger.info(f"无流活动 {self._registered_cnt/len(exhausted_streams)}，已等待 {total_wait_time:.1f} 秒")
                
#             try:
#                 # 非阻塞方式获取流数据
#                 stream_data = self._register_stream.get_nowait()
#                 if stream_data is None or stream_data["exhausted"]:
#                     self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
#                     continue
                    
#                 generator = stream_data["generator"]
#                 self._logger.info(f"消费流 {stream_data['stream_id']} (任务: {stream_data['task_info'].task_id})")
                
#                 if generator is None:
#                     self._logger.error(f"生成器为空，任务: {stream_data['task_info'].task_id}")
#                     # 标记流为已耗尽
#                     exhausted_streams.add(stream_data["stream_id"])
#                     stream_data["exhausted"] = True
#                     self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
#                     continue
                    
#                 task_info = stream_data["task_info"]
#                 content_yielded = False
                
#                 # 处理生成器内容
#                 try:
#                     async for content in generator:
#                         # 更新流的最后活动时间
#                         task_info.update_at = datetime.now()
#                         # 创建输出块并产生
#                         chunk = OutputChunk(content=content, task_info=task_info)
#                         yield chunk
#                         had_activity = True
#                         content_yielded = True
                        
#                 except StopAsyncIteration:
#                     # 生成器已耗尽，标记为已完成
#                     self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")
                    
#                 # 标记流为已耗尽
#                 exhausted_streams.add(stream_data["stream_id"])
#                 stream_data["exhausted"] = True
                
#                 # 如果有内容产生，表示有活动
#                 if content_yielded:
#                     had_activity = True
                    
#             except asyncio.QueueEmpty:
#                 # 队列为空，等待一段时间
#                 await asyncio.sleep(0.2)
#                 wait_time += 0.2
#                 total_wait_time += 0.2
                
#                 if wait_time >= 1:  # 每秒记录一次日志
#                     remaining = self._registered_cnt - len(exhausted_streams)
#                     if remaining > 0:
#                         self._logger.info(f"等待 {remaining} 个流完成，已等待 {total_wait_time:.1f} 秒")
#                     wait_time = 0
#                 continue
                
#             except Exception as e:
#                 # 其他错误处理
#                 self._logger.error(f"处理流时发生错误: {e}")
#                 try:
#                     # 尝试产生错误消息
#                     error_chunk = OutputChunk(
#                         content=f"Error: {str(e)}", task_info=task_info
#                     )
#                     yield error_chunk
#                     had_activity = True
#                 except Exception as yield_error:
#                     self._logger.error(f"无法产生错误消息: {yield_error}")
                    
#                 # 标记流为已耗尽
#                 exhausted_streams.add(stream_data["stream_id"])
#                 stream_data["exhausted"] = True
#                 self._logger.info(f"流 {stream_data['stream_id']} 已耗尽")

#         self._logger.info("All streams exhausted. Ending output stream.")
