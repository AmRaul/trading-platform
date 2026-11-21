import asyncio
import logging
from contextlib import asynccontextmanager
# screener/signals/trend moved to signals service

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.core.redis import init_redis, close_redis
from app.api.routes import auth, bots, trading, positions, trades, websocket, accounts, bybit_accounts, admin, ready_strategies, analytics, me

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    await init_redis()
    logger.info("Redis initialized")

    from app.services.websocket import price_stream_manager
    await price_stream_manager.restore_active_strategies()
    logger.info("Active strategies restored")

    from app.services.signal_scheduler import signal_scheduler
    signal_scheduler.start()

    from app.services.exchange_watch import exchange_watch
    exchange_watch.start()

    # личный Telegram: привязка чатов (/start <код>) и алерты пользователям по их ботам
    from app.services.telegram_bot import telegram_bot
    from app.services.user_alerts import user_alerts
    telegram_bot.start()
    user_alerts.start()

    yield

    await user_alerts.stop()
    await telegram_bot.stop()
    await exchange_watch.stop()
    await signal_scheduler.stop()
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
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(bybit_accounts.router, prefix="/api/bybit-accounts", tags=["bybit-accounts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(ready_strategies.router, prefix="/api/ready-strategies", tags=["ready-strategies"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(me.router, prefix="/api/me", tags=["me"])


@app.get("/")
async def root():
    return {"status": "ok", "message": "Trading Dashboard API"}


@app.get("/health")
async def health():
    """503, если боты не могут работать: БД, Redis, планировщик сигналов или поток цен."""
    from sqlalchemy import text
    from app.application.monitoring.system_health import system_health
    from app.core.database import engine
    from app.core.redis import get_redis
    from app.services.signal_scheduler import signal_scheduler
    from app.services.websocket import price_stream_manager

    async def db_check():
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def redis_check():
        await (await get_redis()).ping()

    healthy, checks = await system_health(
        db_check=db_check, redis_check=redis_check,
        scheduler_running=signal_scheduler.running,
        price_listener_alive=price_stream_manager.listener_alive,
    )
    return JSONResponse(status_code=200 if healthy else 503,
                        content={"status": "healthy" if healthy else "unhealthy", "checks": checks})
