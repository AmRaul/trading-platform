from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import init_db
from app.core.redis import init_redis, close_redis
from app.api.routes import auth, bots, trading, positions, trades, websocket
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Suppress noisy uvicorn logs
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Starting up...")
    await init_redis()
    logger.info("Redis initialized")

    # Restore active strategies (bots with open positions)
    from app.services.websocket import price_stream_manager
    await price_stream_manager.restore_active_strategies()
    logger.info("Active strategies restored")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await close_redis()


app = FastAPI(
    title="Trading Dashboard API",
    description="Trend Pyramiding Trading Bot API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(bots.router, prefix="/api/bots", tags=["bots"])
app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"])
app.include_router(websocket.router, prefix="/api", tags=["websocket"])


@app.get("/")
async def root():
    """Health check"""
    return {"status": "ok", "message": "Trading Dashboard API"}


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}
