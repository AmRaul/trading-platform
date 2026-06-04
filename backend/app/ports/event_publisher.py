from typing import Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(self, event_type: str, data: dict) -> None: ...
