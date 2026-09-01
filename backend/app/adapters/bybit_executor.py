import asyncio
import logging
from typing import Dict, Optional

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
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self._client = HTTP(api_key=api_key, api_secret=api_secret, testnet=testnet)

    async def _run(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    def _side(self, side: str) -> str:
        return "Buy" if side.lower() == "long" else "Sell"

    def _opposite_side(self, side: str) -> str:
        return "Sell" if side.lower() == "long" else "Buy"

    async def _get_avg_price(self, symbol: str) -> Optional[float]:
        response = await self._run(
            lambda: self._client.get_positions(category="linear", symbol=symbol)
        )
        if response.get("retCode") != 0:
            logger.error(f"[Bybit] get_positions failed: {response.get('retMsg')}")
            return None
        rows = response.get("result", {}).get("list", [])
        for row in rows:
            avg_price = row.get("avgPrice")
            if avg_price and float(avg_price) > 0:
                return float(avg_price)
        return None

    async def _push_stop_and_tp(
        self, symbol: str, side: str, avg_price: float, sl_percent: Optional[float], tp_percent: Optional[float]
    ) -> Dict:
        is_long = side.lower() == "long"
        params: Dict = {"category": "linear", "symbol": symbol, "positionIdx": 0}

        if sl_percent is not None:
            sl_price = avg_price * (1 - sl_percent / 100) if is_long else avg_price * (1 + sl_percent / 100)
            params["stopLoss"] = str(round(sl_price, 8))
        if tp_percent is not None:
            tp_price = avg_price * (1 + tp_percent / 100) if is_long else avg_price * (1 - tp_percent / 100)
            params["takeProfit"] = str(round(tp_price, 8))

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
        dca_config: Optional[Dict] = None,
    ) -> Dict:
        # dca_config is Cryptorg-native-DCA-specific — Bybit has no equivalent,
        # our own PositionCalculator/AddPyramidingOrderUseCase already handles
        # averaging by placing separate add_to_position calls, so this is
        # intentionally ignored here.
        #
        # Size against the current ticker, not get_positions() — there's no
        # position yet (that's what we're about to open), and querying it
        # here would either return nothing or, worse, another bot's position
        # on the same symbol/account.
        ticker = await self._run(lambda: self._client.get_tickers(category="linear", symbol=symbol))
        if ticker.get("retCode") != 0 or not ticker.get("result", {}).get("list"):
            return {"success": False, "error": "Failed to get ticker for qty sizing"}
        last_price = float(ticker["result"]["list"][0]["lastPrice"])
        qty = order_volume_usdt / last_price

        order_result = await self._run(
            lambda: self._client.place_order(
                category="linear",
                symbol=symbol,
                side=self._side(side),
                orderType="Market",
                qty=str(round(qty, 8)),
                leverage=str(leverage),
            )
        )
        if order_result.get("retCode") != 0:
            logger.error(f"[Bybit] open_position failed: {order_result.get('retMsg')}")
            return {"success": False, "error": order_result.get("retMsg")}

        order_id = order_result.get("result", {}).get("orderId")

        avg_price = await self._get_avg_price(symbol)
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
        qty = amount_usdt / last_price

        order_result = await self._run(
            lambda: self._client.place_order(
                category="linear",
                symbol=symbol,
                side=self._side(side),
                orderType="Market",
                qty=str(round(qty, 8)),
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
            avg_price = await self._get_avg_price(symbol)
            response = await self._run(
                lambda: self._client.get_positions(category="linear", symbol=symbol)
            )
            rows = response.get("result", {}).get("list", []) if response.get("retCode") == 0 else []
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
            )
        )
        if order_result.get("retCode") != 0:
            logger.error(f"[Bybit] close_position failed: {order_result.get('retMsg')}")
            return {"success": False, "error": order_result.get("retMsg")}

        return {"success": True, "symbol": symbol}

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: Optional[float] = None,
    ) -> Dict:
        avg_price = await self._get_avg_price(symbol)
        if not avg_price:
            return {"success": False, "error": "No open position to update stop/tp for"}
        return await self._push_stop_and_tp(symbol, side, avg_price, sl_percent, tp_percent)
