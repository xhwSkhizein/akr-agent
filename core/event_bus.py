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
        if callback not in self._subscribers[event_type]: # Avoid duplicate subscriptions
            self._subscribers[event_type].append(callback)
            logger.debug(f"Callback {callback.__name__} subscribed to event '{event_type}'")
        else:
            logger.debug(f"Callback {callback.__name__} already subscribed to event '{event_type}'")


    def unsubscribe(self, event_type: str, callback: Callable[..., Any]) -> None:
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Callback {callback.__name__} unsubscribed from event '{event_type}'")
            if not self._subscribers[event_type]: # Remove event type if no subscribers left
                del self._subscribers[event_type]

    async def publish(self, event_type: str, **kwargs: Any) -> None:
        if event_type in self._subscribers:
            logger.debug(f"Publishing event '{event_type}' with data: {kwargs}")
            # Pass the kwargs dictionary itself as 'event_data'
            event_data_dict = kwargs 
            for callback in self._subscribers[event_type]:
                try:
                    # If callback is an async function, await it
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event_data_dict) # Pass the dictionary
                    else:
                        callback(event_data_dict) # Pass the dictionary
                except Exception as e:
                    logger.error(f"Error in event callback {callback.__name__} for event '{event_type}': {e}", exc_info=True)
        else:
            logger.debug(f"No subscribers for event '{event_type}'. Event not published.")
