import aiohttp
from typing import Optional, Dict
from app.core.config import settings
from app.core.encryption import decrypt
import logging

logger = logging.getLogger(__name__)


class CryptorgClient:
    """
    Cryptorg Ghost Bot Webhook API Client

    Uses Ghost Bot mode - no botId required, automatic position matching
    by strategy direction and trading pairs.

    Bybit is used only for price data, while Cryptorg handles actual trading.
    """

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url or getattr(settings, 'CRYPTORG_WEBHOOK_URL', '')
        self.timeout = aiohttp.ClientTimeout(total=30)

    async def _send_webhook(self, payload: dict) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"Cryptorg webhook success: {data}")
                        return data
                    else:
                        error_text = await response.text()
                        logger.error(f"Cryptorg webhook failed [{response.status}]: {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Error sending Cryptorg webhook: {e}")
            return None

    async def open_position(
        self,
        symbol: str,
        side: str,
        order_volume_usdt: float,
        leverage: int = 10,
        sl_percent: float = 5.0,
        tp_percent: float = 3.0,
        dca_config: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Open position with SL and TP in percent. Pass dca_config for native Cryptorg DCA."""
        params: Dict = {
            "strategy": side.lower(),
            "pairs": [symbol],
            "open": {
                "orderVolume": str(order_volume_usdt),
                "leverage": leverage,
                "marginType": "cross",
                "orderType": "Market"
            },
            "close": {
                "enabled": tp_percent is not None,
                "event": "percentage",
                "value": str(tp_percent) if tp_percent is not None else "0"
            },
        }

        if sl_percent is not None:
            params["stop"] = {
                "enabled": True,
                "event": "percentage",
                "value": str(sl_percent),
                "delay": 3
            }
        else:
            params["stop"] = {"enabled": False}

        if dca_config:
            params["dca"] = {
                "enabled": True,
                "max": dca_config.get("max", 10),
                "active": dca_config.get("active", 3),
                "volume": str(dca_config.get("volume", order_volume_usdt)),
                "percent": str(dca_config.get("percent", 2.0)),
                "multiplierVolume": str(dca_config.get("multiplier_volume", 1.0)),
                "multiplierPrice": str(dca_config.get("multiplier_price", 1.0)),
            }

        payload = {"action": "open", "params": params}

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
        return {"success": False, "error": "Failed to open position"}

    async def close_position(
        self,
        symbol: str,
        side: str,
        quantity: float = None
    ) -> Optional[Dict]:
        """Close entire position."""
        payload = {
            "action": "close",
            "params": {
                "strategy": side.lower(),
                "pairs": [symbol],
                "closePosition": True
            }
        }

        logger.info(f"Closing Ghost Bot position: {payload}")
        result = await self._send_webhook(payload)

        if result:
            return {"success": True, "symbol": symbol, "response": result}
        return {"success": False, "error": "Failed to close position"}

    async def add_to_position(
        self,
        symbol: str,
        side: str,
        amount_usdt: float
    ) -> Optional[Dict]:
        """Average into existing position."""
        payload = {
            "action": "average",
            "params": {
                "strategy": side.lower(),
                "pairs": [symbol],
                "amount": str(amount_usdt)
            }
        }

        logger.info(f"Averaging Ghost Bot position: {payload}")
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
        return {"success": False, "error": "Failed to average position"}

    async def update_stop_and_tp(
        self,
        symbol: str,
        side: str,
        sl_percent: float,
        tp_percent: Optional[float] = None,
    ) -> Optional[Dict]:
        """Update SL and optionally TP after averaging. tp_percent=None leaves TP disabled."""
        params: Dict = {
            "strategy": side.lower(),
            "pairs": [symbol],
            "close": {
                "enabled": tp_percent is not None,
                "event": "percentage",
                "value": str(tp_percent) if tp_percent is not None else "0"
            },
        }
        if sl_percent:
            params["stop"] = {
                "enabled": True,
                "event": "percentage",
                "value": str(sl_percent),
                "delay": 3
            }
        else:
            params["stop"] = {"enabled": False}

        payload = {
            "action": "update",
            "params": params
        }

        logger.info(f"Updating Ghost Bot stop/tp: {payload}")
        result = await self._send_webhook(payload)

        if result:
            return {"success": True, "symbol": symbol, "response": result}
        return {"success": False, "error": "Failed to update stop/tp"}


def get_cryptorg_client(credential=None) -> "CryptorgClient":
    if credential is not None:
        return CryptorgClient(webhook_url=decrypt(credential.webhook_url))
    return CryptorgClient()


# Global instance (fallback for single-user mode)
cryptorg_client = CryptorgClient()
