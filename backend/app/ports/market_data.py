from typing import Protocol, Dict, List, runtime_checkable


@runtime_checkable
class MarketData(Protocol):
    async def get_ticker(self, symbol: str) -> Dict: ...

    async def get_klines(self, symbol: str, interval: str, limit: int) -> List[Dict]: ...
