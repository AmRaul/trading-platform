import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import engine, Base
from app.api.routes import screener, signals, trend_signals, trend_symbols, signal_strategies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

SCREENER_INTERVAL = 15 * 60
SIGNAL_UPDATE_INTERVAL = 5 * 60

DEFAULT_TREND_SYMBOLS = [
    "SOLUSDT", "AVAXUSDT", "LINKUSDT",
    "ETHUSDT", "BNBUSDT", "DOTUSDT", "AAVEUSDT",
]

BUILTIN_STRATEGIES = [
    {
        "name": "MOMENTUM",
        "description": "Движение по тренду: цена у хая дня + сильное изменение за 24h",
        "range_min": 65.0, "range_max": None,
        "change_min": 15.0, "change_max": None,
        "vol_1h_min": 15.0, "side": "LONG",
    },
    {
        "name": "REVERSAL",
        "description": "Разворот от экстремума: цена у лоя/хая дня + сильное движение против",
        "range_min": None, "range_max": 25.0,
        "change_min": None, "change_max": -10.0,
        "vol_1h_min": 15.0, "side": "LONG",
    },
    {
        "name": "BREAKOUT",
        "description": "Флэт с аномальным объёмом в середине диапазона — ожидание пробоя",
        "range_min": 30.0, "range_max": 70.0,
        "change_min": -5.0, "change_max": 5.0,
        "vol_1h_min": 15.0, "side": "LONG",
    },
]


async def _seed_trend_symbols():
    from app.core.database import AsyncSessionLocal
    from app.models.trend_symbol import TrendSymbol
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as db:
        count_result = await db.execute(select(func.count()).select_from(TrendSymbol))
        count = count_result.scalar()
        if count == 0:
            for sym in DEFAULT_TREND_SYMBOLS:
                db.add(TrendSymbol(symbol=sym, is_active=True))
            await db.commit()
            logger.info(f"Seeded {len(DEFAULT_TREND_SYMBOLS)} default trend symbols")


async def _seed_signal_strategies():
    from app.core.database import AsyncSessionLocal
    from app.models.signal_strategy import SignalStrategy
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        for s in BUILTIN_STRATEGIES:
            existing = await db.execute(select(SignalStrategy).where(SignalStrategy.name == s["name"]))
            if existing.scalar_one_or_none():
                continue
            db.add(SignalStrategy(is_builtin=True, is_active=True, **s))
        await db.commit()
        logger.info("Built-in signal strategies seeded")


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

    await _seed_trend_symbols()
    await _seed_signal_strategies()

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
    allow_origins=[
        "https://trading.hub-cargo.ru",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(trend_signals.router, prefix="/api/trend-signals", tags=["trend-signals"])
app.include_router(trend_symbols.router, prefix="/api/trend-symbols", tags=["trend-symbols"])
app.include_router(signal_strategies.router, prefix="/api/signal-strategies", tags=["signal-strategies"])


@app.get("/health")
async def health():
    return {"status": "healthy"}
