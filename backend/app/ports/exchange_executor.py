from typing import Protocol, Dict, Optional, runtime_checkable


@runtime_checkable
class ExchangeExecutor(Protocol):
    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict: ...

    async def add_to_position(
        self,
        symbol: str,
        side: str,
        amount_usdt: float,
    ) -> Dict: ...

    async def close_position(
        self,
        symbol: str,
        side: str,
        quantity: Optional[float] = None,
    ) -> Dict: ...

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict: ...
