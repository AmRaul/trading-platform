import asyncio
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Optional, Tuple

from pybit.unified_trading import HTTP

logger = logging.getLogger(__name__)


class BybitExecutorAdapter:
    """Adapts pybit's unified_trading HTTP client to the ExchangeExecutor port.

    Unlike Cryptorg (which accepts SL/TP as percent offsets in the same
    webhook that opens the position), Bybit's set_trading_stop needs
    ABSOLUTE prices — and those aren't known until the market order fills.
    So open_position/add_to_position place the order WITHOUT SL/TP, then
    fetch the real avgPrice via get_positions() and push SL/TP as a second
    call. Two API calls instead of one, but SL/TP end up computed from the
    actual fill price, not the pre-slippage entry estimate.

    hedge=True — режим хеджа Bybit (positionIdx 1 — LONG, 2 — SHORT): LONG и
    SHORT по одной монете живут одновременно (straddle-бот). По умолчанию —
    односторонний режим (positionIdx 0), как у остальных ботов.
    """

    # symbol -> (qtyStep, minOrderQty, tickSize); биржевые параметры меняются редко
    _instruments: Dict[str, Tuple[Decimal, Decimal, Decimal]] = {}

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, hedge: bool = False):
        self._client = HTTP(api_key=api_key, api_secret=api_secret, testnet=testnet)
        self._testnet = testnet
        self._hedge = hedge

    def _idx(self, side: str) -> int:
        if not self._hedge:
            return 0
        return 1 if side.lower() == "long" else 2

    async def ensure_hedge_mode(self, symbol: str) -> Dict:
        """Переключает монету в режим хеджа (нужен до открытия позиций)."""
        resp = await self._run(lambda: self._client.switch_position_mode(category="linear", symbol=symbol, mode=3))
        # 110025 — режим уже такой
        if resp.get("retCode") in (0, 110025):
            return {"success": True}
        logger.error(f"[Bybit] switch_position_mode failed: {resp.get('retMsg')}")
        return {"success": False, "error": resp.get("retMsg")}

    async def _instrument(self, symbol: str) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
        key = f"{'test' if self._testnet else 'main'}:{symbol}"
        if key not in self._instruments:
            resp = await self._run(lambda: self._client.get_instruments_info(category="linear", symbol=symbol))
            rows = resp.get("result", {}).get("list", []) if resp.get("retCode") == 0 else []
            if not rows:
                logger.error(f"[Bybit] get_instruments_info failed for {symbol}: {resp.get('retMsg')}")
                return None
            lot, price = rows[0]["lotSizeFilter"], rows[0]["priceFilter"]
            self._instruments[key] = (Decimal(lot["qtyStep"]), Decimal(lot["minOrderQty"]), Decimal(price["tickSize"]))
        return self._instruments[key]

    async def _qty_for_usdt(self, symbol: str, amount_usdt: float, price: float) -> Tuple[Optional[str], str]:
        """Объём в монетах, округлённый вниз до qtyStep. Bybit отклоняет qty
        не кратный шагу лота. Возвращает (qty, ошибка)."""
        inst = await self._instrument(symbol)
        if not inst:
            return None, f"No instrument info for {symbol}"
        step, min_qty, _ = inst
        qty = (Decimal(str(amount_usdt)) / Decimal(str(price)) / step).to_integral_value(ROUND_DOWN) * step
        if qty < min_qty:
            return None, (f"{amount_usdt:.2f} USDT < минимального лота {symbol}: "
                          f"{min_qty} ≈ {float(min_qty) * price:.2f} USDT")
        return format(qty.normalize(), "f"), ""

    async def _price_str(self, symbol: str, price: float) -> str:
        inst = await self._instrument(symbol)
        if not inst:
            return str(round(price, 8))
        tick = inst[2]
        return format(((Decimal(str(price)) / tick).to_integral_value() * tick).normalize(), "f")

    async def _run(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    def _side(self, side: str) -> str:
        return "Buy" if side.lower() == "long" else "Sell"

    def _opposite_side(self, side: str) -> str:
        return "Sell" if side.lower() == "long" else "Buy"

    async def _position_rows(self, symbol: str, side: Optional[str] = None) -> list:
        """Строки позиций по монете; в режиме хеджа — только нужной стороны."""
        response = await self._run(
            lambda: self._client.get_positions(category="linear", symbol=symbol)
        )
        if response.get("retCode") != 0:
            logger.error(f"[Bybit] get_positions failed: {response.get('retMsg')}")
            return []
        rows = response.get("result", {}).get("list", [])
        if self._hedge and side:
            rows = [r for r in rows if r.get("positionIdx") == self._idx(side)]
        return rows

    async def _get_avg_price(self, symbol: str, side: Optional[str] = None) -> Optional[float]:
        for row in await self._position_rows(symbol, side):
            avg_price = row.get("avgPrice")
            if avg_price and float(avg_price) > 0:
                return float(avg_price)
        return None

    async def _push_stop_and_tp(
        self, symbol: str, side: str, avg_price: float, sl_percent: Optional[float], tp_percent: Optional[float]
    ) -> Dict:
        is_long = side.lower() == "long"
        params: Dict = {"category": "linear", "symbol": symbol, "positionIdx": self._idx(side)}

        if sl_percent is not None:
            sl_price = avg_price * (1 - sl_percent / 100) if is_long else avg_price * (1 + sl_percent / 100)
            params["stopLoss"] = await self._price_str(symbol, sl_price)
        if tp_percent is not None:
            tp_price = avg_price * (1 + tp_percent / 100) if is_long else avg_price * (1 - tp_percent / 100)
            params["takeProfit"] = await self._price_str(symbol, tp_price)

        if "stopLoss" not in params and "takeProfit" not in params:
            return {"success": True}

        response = await self._run(lambda: self._client.set_trading_stop(**params))
        if response.get("retCode") != 0:
            logger.error(f"[Bybit] set_trading_stop failed: {response.get('retMsg')}")
            return {"success": False, "error": response.get("retMsg")}
        return {"success": True}

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int,
        sl_percent: float,
        tp_percent: float,
    ) -> Dict:
        # Size against the current ticker, not get_positions() — there's no
        # position yet (that's what we're about to open), and querying it
        # here would either return nothing or, worse, another bot's position
        # on the same symbol/account.
        ticker = await self._run(lambda: self._client.get_tickers(category="linear", symbol=symbol))
        if ticker.get("retCode") != 0 or not ticker.get("result", {}).get("list"):
            return {"success": False, "error": "Failed to get ticker for qty sizing"}
        last_price = float(ticker["result"]["list"][0]["lastPrice"])
        qty, err = await self._qty_for_usdt(symbol, order_volume_usdt, last_price)
        if qty is None:
            logger.error(f"[Bybit] open_position: {err}")
            return {"success": False, "error": err}

        order_result = await self._run(
            lambda: self._client.place_order(
                category="linear",
                symbol=symbol,
                side=self._side(side),
                orderType="Market",
                qty=qty,
                leverage=str(leverage),
                positionIdx=self._idx(side),
            )
        )
        if order_result.get("retCode") != 0:
            logger.error(f"[Bybit] open_position failed: {order_result.get('retMsg')}")
            return {"success": False, "error": order_result.get("retMsg")}

        order_id = order_result.get("result", {}).get("orderId")

        avg_price = await self._get_avg_price(symbol, side)
        if avg_price:
            await self._push_stop_and_tp(symbol, side, avg_price, sl_percent, tp_percent)
        else:
            logger.warning(f"[Bybit] Could not fetch avgPrice for {symbol} after open — SL/TP not set")

        return {"success": True, "orderId": order_id, "symbol": symbol, "side": side}

    async def add_to_position(self, symbol: str, side: str, amount_usdt: float) -> Dict:
        ticker = await self._run(lambda: self._client.get_tickers(category="linear", symbol=symbol))
        if ticker.get("retCode") != 0 or not ticker.get("result", {}).get("list"):
            return {"success": False, "error": "Failed to get ticker for qty sizing"}
        last_price = float(ticker["result"]["list"][0]["lastPrice"])
        qty, err = await self._qty_for_usdt(symbol, amount_usdt, last_price)
        if qty is None:
            logger.error(f"[Bybit] add_to_position: {err}")
            return {"success": False, "error": err}

        order_result = await self._run(
            lambda: self._client.place_order(
                category="linear",
                symbol=symbol,
                side=self._side(side),
                orderType="Market",
                qty=qty,
                positionIdx=self._idx(side),
            )
        )
        if order_result.get("retCode") != 0:
            logger.error(f"[Bybit] add_to_position failed: {order_result.get('retMsg')}")
            return {"success": False, "error": order_result.get("retMsg")}

        return {
            "success": True,
            "orderId": order_result.get("result", {}).get("orderId"),
            "symbol": symbol,
            "side": side,
            "quantity": amount_usdt,
        }

    async def close_position(self, symbol: str, side: str, quantity: Optional[float] = None) -> Dict:
        if quantity is None:
            rows = await self._position_rows(symbol, side)
            size = float(rows[0]["size"]) if rows and rows[0].get("size") else None
            if not size:
                return {"success": False, "error": "No open position size found to close"}
            qty = size
        else:
            qty = quantity

        order_result = await self._run(
            lambda: self._client.place_order(
                category="linear",
                symbol=symbol,
                side=self._opposite_side(side),
                orderType="Market",
                qty=str(qty),
                reduceOnly=True,
                positionIdx=self._idx(side),
            )
        )
        if order_result.get("retCode") != 0:
            logger.error(f"[Bybit] close_position failed: {order_result.get('retMsg')}")
            return {"success": False, "error": order_result.get("retMsg")}

        return {"success": True, "symbol": symbol}

    async def get_open_position_size(self, symbol: str, side: str) -> Optional[float]:
        response = await self._run(
            lambda: self._client.get_positions(category="linear", symbol=symbol)
        )
        if response.get("retCode") != 0:
            logger.error(f"[Bybit] get_positions failed: {response.get('retMsg')}")
            return None
        wanted = self._side(side)
        size = 0.0
        for row in response.get("result", {}).get("list", []):
            if row.get("side") == wanted and row.get("size"):
                size += float(row["size"])
        return size

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: Optional[float] = None,
    ) -> Dict:
        avg_price = await self._get_avg_price(symbol, side)
        if not avg_price:
            return {"success": False, "error": "No open position to update stop/tp for"}
        return await self._push_stop_and_tp(symbol, side, avg_price, sl_percent, tp_percent)
