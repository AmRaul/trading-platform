import logging
import uuid
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Bybit linear, taker — все ордера бота рыночные; та же ставка, что в бэктестах
# (services/backtester/research), чтобы форвард-тест сравнивался с ними напрямую
PAPER_TAKER_FEE = 0.00055


class PaperExecutorAdapter:
    """Бумажная торговля: ExchangeExecutor без реальных ордеров.

    Весь конвейер бота (сигнал → вход → доборы/страховочные → стоп/трейлинг/TP)
    работает как обычно: цены исполнения use cases берут с живого тикера Bybit,
    стоп и тейк бэкенд ловит по цене сам. Адаптер только подтверждает ордера.

    fee_rate — комиссия на каждое исполнение; ClosePositionUseCase вычитает её
    из PnL сделки (у реальных бирж атрибута нет — их PnL пишется как раньше).
    """

    fee_rate = PAPER_TAKER_FEE

    def _ok(self, action: str, symbol: str, side: str, **extra) -> Dict:
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        logger.info(f"[PAPER] {action} {symbol} {side} {extra} → {order_id}")
        return {"success": True, "orderId": order_id, "symbol": symbol, "side": side, **extra}

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict:
        return self._ok("open", symbol, side, size_usdt=order_volume_usdt)

    async def add_to_position(self, symbol: str, side: str, amount_usdt: float) -> Dict:
        return self._ok("add", symbol, side, quantity=amount_usdt)

    async def close_position(self, symbol: str, side: str, quantity: Optional[float] = None) -> Dict:
        return self._ok("close", symbol, side)

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: Optional[float] = None,
    ) -> Dict:
        # Стоп и тейк бэкенд и так ловит по цене — на бирже нечего обновлять
        return {"success": True}

    async def get_open_position_size(self, symbol: str, side: str) -> Optional[float]:
        # Биржи нет — сверять не с чем; None отключает сверку
        return None
