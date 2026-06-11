import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.redis import init_redis, close_redis
from app.api.routes import auth, bots, trading, positions, trades, websocket, screener, signals, trend_signals, profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

SCREENER_INTERVAL = 15 * 60   # 15 минут
SIGNAL_UPDATE_INTERVAL = 5 * 60  # 5 минут


async def _screener_loop():
    """Run screener scan every SCREENER_INTERVAL seconds."""
    from app.application.screener.scan_market import ScanMarketUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal

    use_case = ScanMarketUseCase(BybitMarketDataAdapter())

    # Первый запуск сразу при старте
    await asyncio.sleep(5)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Screener loop error: {e}", exc_info=True)
        await asyncio.sleep(SCREENER_INTERVAL)


async def _signal_update_loop():
    """Update prices for PENDING signals every 5 minutes."""
    from app.application.screener.update_signal_prices import UpdateSignalPricesUseCase
    from app.adapters.bybit_market_data import BybitMarketDataAdapter
    from app.core.database import AsyncSessionLocal

    use_case = UpdateSignalPricesUseCase(BybitMarketDataAdapter())

    await asyncio.sleep(60)  # первый запуск через минуту после старта
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await use_case.execute(db)
        except Exception as e:
            logger.error(f"Signal update loop error: {e}", exc_info=True)
        await asyncio.sleep(SIGNAL_UPDATE_INTERVAL)


async def _trend_signal_loop():
    """Scan liquid alts for 4H/1H/15m trend signals every 15 minutes."""
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
            logger.error(f"Trend signal loop error: {e}", exc_info=True)
        await asyncio.sleep(SCREENER_INTERVAL)


async def _trend_update_loop():
    """Check OPEN trend signals for stop/EMA exit every 5 minutes."""
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
    logger.info("Starting up...")
    await init_redis()
    logger.info("Redis initialized")

    from app.services.websocket import price_stream_manager
    await price_stream_manager.restore_active_strategies()
    logger.info("Active strategies restored")

    screener_task = asyncio.create_task(_screener_loop())
    logger.info("Screener scheduler started (every 15 min)")

    signal_task = asyncio.create_task(_signal_update_loop())
    logger.info("Signal price updater started (every 5 min)")

    trend_scan_task = asyncio.create_task(_trend_signal_loop())
    logger.info("Trend signal scanner started (every 15 min)")

    trend_update_task = asyncio.create_task(_trend_update_loop())
    logger.info("Trend signal updater started (every 5 min)")

    yield

    screener_task.cancel()
    signal_task.cancel()
    trend_scan_task.cancel()
    trend_update_task.cancel()
    await price_stream_manager.stop()
    logger.info("Shutting down...")
    await close_redis()


app = FastAPI(
    title="Trading Dashboard API",
    description="Trend Pyramiding Trading Bot API",
    version="1.0.0",
    lifespan=lifespan,
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    logger.error(f"[422] {request.method} {request.url} — {errors}")
    return JSONResponse(status_code=422, content={"detail": errors})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(websocket.router, prefix="/api", tags=["websocket"])
app.include_router(screener.router, prefix="/api/screener", tags=["screener"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(trend_signals.router, prefix="/api/trend-signals", tags=["trend-signals"])
app.include_router(profile.router, prefix="/api/profile", tags=["profile"])


@app.get("/")
async def root():
    return {"status": "ok", "message": "Trading Dashboard API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
