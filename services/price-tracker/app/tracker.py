"""
PriceTracker — subscribes to exchange streams, writes prices to Redis,
and publishes to Redis pub/sub channel prices:{exchange}:{symbol}.

Execution service subscribes to those channels to drive strategy engines.
Adding a new exchange = implement PriceStream port + register adapter here.
"""
from typing import Dict, Set
import asyncio
import json
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

PRICE_KEY = "price:{symbol}"
PRICE_CHANNEL = "prices:{exchange}:{symbol}"


class PriceTracker:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis
        # exchange_name -> stream adapter
        self._streams: Dict[str, object] = {}
        # exchange -> set of symbols
        self._subscriptions: Dict[str, Set[str]] = {}

    def register_exchange(self, name: str, stream) -> None:
        """Register a PriceStream adapter for an exchange."""
        self._streams[name] = stream
        self._subscriptions[name] = set()
        logger.info(f"Registered exchange: {name}")

    async def subscribe(self, exchange: str, symbol: str) -> None:
        stream = self._streams.get(exchange)
        if not stream:
            raise ValueError(f"Unknown exchange: {exchange}")
        if symbol in self._subscriptions[exchange]:
            return
        await stream.subscribe(symbol, self._on_price)
        self._subscriptions[exchange].add(symbol)

    async def unsubscribe(self, exchange: str, symbol: str) -> None:
        stream = self._streams.get(exchange)
        if stream:
            await stream.unsubscribe(symbol)
        if exchange in self._subscriptions:
            self._subscriptions[exchange].discard(symbol)

    async def _on_price(self, exchange: str, symbol: str, price: float) -> None:
        key = PRICE_KEY.format(symbol=symbol)
        channel = PRICE_CHANNEL.format(exchange=exchange, symbol=symbol)
        payload = json.dumps({"exchange": exchange, "symbol": symbol, "price": price})
        async with self._redis.pipeline() as pipe:
            pipe.set(key, str(price), ex=60)
            pipe.publish(channel, payload)
            await pipe.execute()

    async def close(self) -> None:
        for stream in self._streams.values():
            await stream.close()
