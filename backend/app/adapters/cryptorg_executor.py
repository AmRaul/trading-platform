from typing import Dict, Optional
from app.services.cryptorg import cryptorg_client


class CryptorgExecutorAdapter:
    """Adapts CryptorgClient to the ExchangeExecutor port."""

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict:
        return await cryptorg_client.open_position(
            symbol=symbol,
            side=side,
            order_volume_usdt=order_volume_usdt,
            leverage=leverage,
            sl_percent=sl_percent,
            tp_percent=tp_percent,
        )

    async def add_to_position(self, symbol: str, side: str, amount_usdt: float) -> Dict:
        return await cryptorg_client.add_to_position(
            symbol=symbol,
            side=side,
            amount_usdt=amount_usdt,
        )

    async def close_position(self, symbol: str, side: str, quantity: Optional[float] = None) -> Dict:
        return await cryptorg_client.close_position(symbol=symbol, side=side, quantity=quantity)

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict:
        return await cryptorg_client.update_stop_and_tp(
            symbol=symbol,
            side=side,
            sl_percent=sl_percent,
            tp_percent=tp_percent,
        )
