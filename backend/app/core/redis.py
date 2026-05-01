import redis.asyncio as aioredis
from app.core.config import settings
from typing import Optional
import json

redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Get Redis client"""
    return redis_client


async def init_redis():
    """Initialize Redis connection"""
    global redis_client
    redis_client = await aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )


async def close_redis():
    """Close Redis connection"""
    if redis_client:
        await redis_client.close()


class RedisKeys:
    """Redis key patterns"""

    @staticmethod
    def position(bot_id: str) -> str:
        return f"position:{bot_id}"

    @staticmethod
    def live_price(symbol: str) -> str:
        return f"price:{symbol}"

    @staticmethod
    def bot_state(bot_id: str) -> str:
        return f"bot_state:{bot_id}"


async def set_position_state(bot_id: str, data: dict):
    """Store position state in Redis"""
    key = RedisKeys.position(bot_id)
    await redis_client.set(key, json.dumps(data))


async def get_position_state(bot_id: str) -> Optional[dict]:
    """Get position state from Redis"""
    key = RedisKeys.position(bot_id)
    data = await redis_client.get(key)
    return json.loads(data) if data else None


async def delete_position_state(bot_id: str):
    """Delete position state from Redis"""
    key = RedisKeys.position(bot_id)
    await redis_client.delete(key)


async def set_live_price(symbol: str, price: float):
    """Store live price in Redis"""
    key = RedisKeys.live_price(symbol)
    await redis_client.set(key, str(price), ex=60)


async def get_live_price(symbol: str) -> Optional[float]:
    """Get live price from Redis"""
    key = RedisKeys.live_price(symbol)
    price = await redis_client.get(key)
    return float(price) if price else None
