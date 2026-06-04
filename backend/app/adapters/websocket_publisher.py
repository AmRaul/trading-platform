import logging

logger = logging.getLogger(__name__)

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        from app.services.websocket import manager
        _manager = manager
    return _manager


class WebSocketPublisherAdapter:
    """Adapts ConnectionManager.broadcast_event to the EventPublisher port."""

    async def publish(self, event_type: str, data: dict) -> None:
        try:
            await _get_manager().broadcast_event(event_type, data)
        except Exception as e:
            logger.error(f"Error publishing event {event_type}: {e}")
