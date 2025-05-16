from typing import Callable, Dict, List, Any
import logging
import asyncio

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable[..., Any]]] = {}

    def subscribe(self, event_type: str, callback: Callable[..., Any]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if (
            callback not in self._subscribers[event_type]
        ):  # Avoid duplicate subscriptions
            self._subscribers[event_type].append(callback)
            logger.debug(
                f"Callback {callback.__name__} subscribed to event '{event_type}'"
            )
        else:
            logger.debug(
                f"Callback {callback.__name__} already subscribed to event '{event_type}'"
            )

    def unsubscribe(self, event_type: str, callback: Callable[..., Any]) -> None:
        if (
            event_type in self._subscribers
            and callback in self._subscribers[event_type]
        ):
            self._subscribers[event_type].remove(callback)
            logger.debug(
                f"Callback {callback.__name__} unsubscribed from event '{event_type}'"
            )
            if not self._subscribers[
                event_type
            ]:  # Remove event type if no subscribers left
                del self._subscribers[event_type]

    async def publish(self, event_type: str, **kwargs: Any) -> None:
        """发布事件到所有订阅者"""
        if event_type in self._subscribers:
            failed_callbacks = []
            event_data_dict = kwargs
            for callback in self._subscribers[event_type]:
                try:
                    await callback(event_data_dict)
                except asyncio.CancelledError:
                    # 重新抛出取消异常，允许正确处理任务取消
                    raise
                except Exception as e:
                    logger.error(
                        f"事件 '{event_type}' 回调执行失败: {e}", exc_info=True
                    )
                    failed_callbacks.append((callback, str(e)))
                    # 继续执行其他回调，不中断

            # 可选：实现重试逻辑
            # if failed_callbacks and self._retry_policy.should_retry(event_type):
            #     await self._retry_failed_callbacks(
            #         event_type, event_data_dict, failed_callbacks
            #     )

        #     event_data_dict = kwargs
        #     for callback in self._subscribers[event_type]:
        #         try:
        #             # If callback is an async function, await it
        #             if asyncio.iscoroutinefunction(callback):
        #                 await callback(event_data_dict) # Pass the dictionary
        #             else:
        #                 callback(event_data_dict) # Pass the dictionary
        #         except Exception as e:
        #             logger.error(f"Error in event callback {callback.__name__} for event '{event_type}': {e}", exc_info=True)
        # else:
        #     logger.debug(f"No subscribers for event '{event_type}'. Event not published.")
