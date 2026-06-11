import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import engine, Base
from app.api.routes import screener, signals, trend_signals

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

SCREENER_INTERVAL = 15 * 60
SIGNAL_UPDATE_INTERVAL = 5 * 60


async def _screener_loop():
    from app.application.screener.scan_market import ScanMarketUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal
    use_case = ScanMarketUseCase(BybitMarketDataAdapter())
    await asyncio.sleep(5)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Screener loop error: {e}", exc_info=True)
        await asyncio.sleep(SCREENER_INTERVAL)


async def _signal_update_loop():
    from app.application.screener.update_signal_prices import UpdateSignalPricesUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal
    use_case = UpdateSignalPricesUseCase(BybitMarketDataAdapter())
    await asyncio.sleep(60)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Signal update loop error: {e}", exc_info=True)
        await asyncio.sleep(SIGNAL_UPDATE_INTERVAL)


async def _trend_scan_loop():
    from app.application.trend.scan_trend_signals import ScanTrendSignalsUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal
    use_case = ScanTrendSignalsUseCase(BybitMarketDataAdapter())
    await asyncio.sleep(15)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Trend scan loop error: {e}", exc_info=True)
        await asyncio.sleep(SCREENER_INTERVAL)


async def _trend_update_loop():
    from app.application.trend.update_trend_signals import UpdateTrendSignalsUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal
    use_case = UpdateTrendSignalsUseCase(BybitMarketDataAdapter())
    await asyncio.sleep(90)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Trend update loop error: {e}", exc_info=True)
        await asyncio.sleep(SIGNAL_UPDATE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    t1 = asyncio.create_task(_screener_loop())
    t2 = asyncio.create_task(_signal_update_loop())
    t3 = asyncio.create_task(_trend_scan_loop())
    t4 = asyncio.create_task(_trend_update_loop())
    logger.info("Background loops started")

    yield

    for t in [t1, t2, t3, t4]:
        t.cancel()


app = FastAPI(title="Signals Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(trend_signals.router, prefix="/api/trend-signals", tags=["trend-signals"])


@app.get("/health")
async def health():
    return {"status": "healthy"}
