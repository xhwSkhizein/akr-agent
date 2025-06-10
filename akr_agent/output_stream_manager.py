import asyncio
import uuid
import logging
from typing import Dict, Any, AsyncGenerator
from datetime import datetime

from .task_state import TaskInfo


class OutputChunk:
    """Single output chunk, containing content and corresponding metadata reference"""

    def __init__(self, content: str, task_info: TaskInfo):
        self.content = content
        self.task_info = task_info

    def dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation"""
        return {"content": self.content, "task_info": self.task_info.to_dict()}

class OutputStreamManager:
    """Output stream manager, responsible for managing and processing the output of multiple asynchronous generators"""

    def __init__(self, logger: logging.Logger, stream_registration_timeout: float = 1.0):
        """
        Initialize the output stream manager
        Args:
            logger: Logger
            stream_registration_timeout: When all known streams have been processed, the timeout for waiting for new stream registrations (seconds)
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
        Register a new output stream. The stream will be processed in the order of registration.

        Args:
            async_generator: Asynchronous generator
            task_info: Task information

        Returns:
            stream_id: Stream ID
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
        Get and process all output streams in the order of registration.

        This method will sequentially take each registered stream from the queue and fully consume
        all its output before processing the next stream. When all registered streams have been processed,
        and no new streams are registered within a certain timeout period, this asynchronous generator ends.
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
                        yield OutputChunk(content="...", task_info=None)
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
