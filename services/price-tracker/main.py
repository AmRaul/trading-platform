import asyncio
import logging
import redis.asyncio as aioredis
import uvicorn

from app.config import settings
from app.tracker import PriceTracker
from app.adapters.bybit_stream import BybitPriceStream
from app.api import app, set_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    redis = await aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )

    tracker = PriceTracker(redis)
    tracker.register_exchange("bybit", BybitPriceStream(testnet=settings.BYBIT_TESTNET))
    # Future exchanges: tracker.register_exchange("binance", BinancePriceStream())
    #                   tracker.register_exchange("okx", OkxPriceStream())

    set_tracker(tracker)

    # Subscribe to default symbols on startup (optional)
    if settings.DEFAULT_SYMBOLS:
        for sym in settings.DEFAULT_SYMBOLS.split(","):
            sym = sym.strip()
            if sym:
                await tracker.subscribe("bybit", sym)
                logger.info(f"Auto-subscribed bybit:{sym}")

    config = uvicorn.Config(app, host="0.0.0.0", port=8010, log_level="warning")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await tracker.close()
        await redis.close()


if __name__ == "__main__":
    asyncio.run(main())
