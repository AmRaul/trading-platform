from typing import Protocol, Dict, List, Optional, runtime_checkable


@runtime_checkable
class MarketData(Protocol):
    async def get_ticker(self, symbol: str) -> Dict: ...

    async def get_klines(self, symbol: str, interval: str, limit: int, end_ms: Optional[int] = None) -> List[Dict]: ...

    async def get_klines_range(self, symbol: str, interval: str, start_ms: int, end_ms: int) -> List[Dict]: ...
