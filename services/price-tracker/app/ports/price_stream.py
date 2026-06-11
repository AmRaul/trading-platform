from typing import Protocol, Callable, Awaitable


class PriceStream(Protocol):
    """Port: connects to an exchange and streams live prices."""

    async def subscribe(self, symbol: str, callback: Callable[[str, str, float], Awaitable[None]]) -> None:
        """Subscribe to price updates for symbol.

        callback(exchange, symbol, price)
        """
        ...

    async def unsubscribe(self, symbol: str) -> None: ...

    async def close(self) -> None: ...
