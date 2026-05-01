import aiohttp
from typing import Optional, Dict
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class CryptorgClient:
    """
    Cryptorg Ghost Bot Webhook API Client

    Uses Ghost Bot mode - no botId required, automatic position matching
    by strategy direction and trading pairs.

    Bybit is used only for price data, while Cryptorg handles actual trading.
    """

    def __init__(self):
        self.webhook_url = getattr(settings, 'CRYPTORG_WEBHOOK_URL', '')
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def _send_webhook(self, payload: dict) -> Optional[dict]:
        """
        Send webhook POST request to Cryptorg Ghost Bot

        Args:
            payload: Request payload (dict) in Ghost Bot format

        Returns:
            Response data or None if failed
        """
        try:
            headers = {
                'Content-Type': 'application/json',
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers
                ) as response:

                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Cryptorg Ghost Bot webhook success: {data}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Cryptorg Ghost Bot webhook failed [{response.status}]: {error_text}")
                        return None

        except Exception as e:
            logger.error(f"Error sending Cryptorg Ghost Bot webhook: {e}")
            return None

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int = 10,
        config: dict = None
    ) -> Optional[Dict]:
        """
        Open a new position via Cryptorg Ghost Bot webhook

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "long" or "short"
            order_volume_usdt: First order size in USDT
            leverage: Leverage multiplier
            config: Optional strategy config for DCA, close, stop settings

        Returns:
            Response with order info or None if failed
        """
        # Ghost Bot format - correct structure with action and params
        payload = {
            "action": "open",
            "params": {
                "strategy": side.lower(),  # "long" or "short"
                "pairs": [symbol],
                "open": {
                    "orderVolume": str(order_volume_usdt),
                    "leverage": leverage,
                    "marginType": "cross",
                    "orderType": "Market"
                },
                "dca": config.get("dca", {
                    "enabled": False
                }) if config else {"enabled": False},
                "close": config.get("close", {
                    "enabled": False
                }) if config else {"enabled": False},
                "stop": config.get("stop", {
                    "enabled": False
                }) if config else {"enabled": False}
            }
        }

        logger.info(f"Opening Ghost Bot position: {payload}")

        result = await self._send_webhook(payload)

        if result:
            return {
                "success": True,
                "orderId": result.get("orderId") or result.get("id"),
                "symbol": symbol,
                "side": side,
                "quantity": order_volume_usdt,
                "response": result
            }
        else:
            return {
                "success": False,
                "error": "Failed to open position"
            }

    async def close_position(
        self,
        symbol: str,
        side: str,
        quantity: float = None
    ) -> Optional[Dict]:
        """
        Close an existing position via Cryptorg Ghost Bot webhook

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "LONG" or "SHORT" (original position side)
            quantity: Not used in Ghost Bot (closes entire position)

        Returns:
            Response with close info or None if failed
        """
        # Ghost Bot close format - correct structure with action and params
        payload = {
            "action": "close",
            "params": {
                "strategy": side.lower(),  # "long" or "short"
                "pairs": [symbol]
            }
        }

        logger.info(f"Closing Ghost Bot position: {payload}")

        result = await self._send_webhook(payload)

        if result:
            return {
                "success": True,
                "orderId": result.get("orderId") or result.get("id"),
                "symbol": symbol,
                "response": result
            }
        else:
            return {
                "success": False,
                "error": "Failed to close position"
            }

    async def add_to_position(
        self,
        symbol: str,
        side: str,
        amount_usdt: float
    ) -> Optional[Dict]:
        """
        Add to existing position (pyramiding/averaging) via Ghost Bot

        Args:
            symbol: Trading pair
            side: "long" or "short"
            amount_usdt: Additional size to add in USDT

        Returns:
            Response with order info
        """
        # Ghost Bot averaging/pyramiding format - correct structure with action and params
        payload = {
            "action": "add",
            "params": {
                "strategy": side.lower(),  # "long" or "short"
                "pairs": [symbol],
                "amount": str(amount_usdt)  # Volume in USDT
            }
        }

        logger.info(f"Adding to Ghost Bot position (pyramiding): {payload}")

        result = await self._send_webhook(payload)

        if result:
            return {
                "success": True,
                "orderId": result.get("orderId") or result.get("id"),
                "symbol": symbol,
                "side": side,
                "quantity": amount_usdt,
                "response": result
            }
        else:
            return {
                "success": False,
                "error": "Failed to add to position"
            }

    async def set_stop_loss(
        self,
        symbol: str,
        side: str,
        stop_price: float
    ) -> Optional[Dict]:
        """
        Set or update stop-loss for an existing position via Ghost Bot

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "long" or "short"
            stop_price: Stop-loss trigger price

        Returns:
            Response with stop-loss info or None if failed
        """
        # Ghost Bot format for setting stop-loss
        payload = {
            "action": "update_stop",
            "params": {
                "strategy": side.lower(),  # "long" or "short"
                "pairs": [symbol],
                "stop": {
                    "enabled": True,
                    "stopLoss": {
                        "enabled": True,
                        "type": "market",  # Market order when triggered
                        "price": str(stop_price)
                    }
                }
            }
        }

        logger.info(f"Setting Ghost Bot stop-loss: {payload}")

        result = await self._send_webhook(payload)

        if result:
            return {
                "success": True,
                "symbol": symbol,
                "stop_price": stop_price,
                "response": result
            }
        else:
            return {
                "success": False,
                "error": "Failed to set stop-loss"
            }

    async def cancel_stop_loss(
        self,
        symbol: str,
        side: str
    ) -> Optional[Dict]:
        """
        Cancel stop-loss for an existing position via Ghost Bot

        Args:
            symbol: Trading pair
            side: "long" or "short"

        Returns:
            Response or None if failed
        """
        # Ghost Bot format for canceling stop-loss
        payload = {
            "action": "update_stop",
            "params": {
                "strategy": side.lower(),
                "pairs": [symbol],
                "stop": {
                    "enabled": False
                }
            }
        }

        logger.info(f"Canceling Ghost Bot stop-loss: {payload}")

        result = await self._send_webhook(payload)

        if result:
            return {
                "success": True,
                "symbol": symbol,
                "response": result
            }
        else:
            return {
                "success": False,
                "error": "Failed to cancel stop-loss"
            }


# Global instance
cryptorg_client = CryptorgClient()
