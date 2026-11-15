import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock

# Set required env vars before any app imports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")

# Mock heavy infrastructure modules so tests don't need real DB/Redis/asyncpg
sys.modules.setdefault("asyncpg", MagicMock())

# Use real SQLAlchemy declarative Base so model constructors work correctly
from sqlalchemy.orm import declarative_base as _declarative_base
_RealBase = _declarative_base()

_mock_db = MagicMock()
_mock_db.Base = _RealBase
_mock_db.get_db = AsyncMock()
_mock_db.engine = MagicMock()
_mock_db.AsyncSessionLocal = MagicMock()
sys.modules["app.core.database"] = _mock_db

_mock_redis = MagicMock()
_mock_redis.set_position_state = AsyncMock()
_mock_redis.get_position_state = AsyncMock(return_value=None)
_mock_redis.delete_position_state = AsyncMock()
sys.modules["app.core.redis"] = _mock_redis

# Mock external service modules
sys.modules.setdefault("pybit", MagicMock())
sys.modules.setdefault("pybit.unified_trading", MagicMock())

_mock_bybit = MagicMock()
_mock_bybit.bybit_client = MagicMock()
_mock_bybit.bybit_client.get_ticker = AsyncMock()
sys.modules["app.services.bybit"] = _mock_bybit

_mock_cryptorg = MagicMock()
_mock_cryptorg.cryptorg_client = MagicMock()
_mock_cryptorg.cryptorg_client.open_position = AsyncMock()
_mock_cryptorg.cryptorg_client.update_stop_and_tp = AsyncMock()
_mock_cryptorg.cryptorg_client.add_to_position = AsyncMock()
_mock_cryptorg.cryptorg_client.close_position = AsyncMock()
_mock_cryptorg.get_cryptorg_client = MagicMock(return_value=_mock_cryptorg.cryptorg_client)
sys.modules["app.services.cryptorg"] = _mock_cryptorg

_mock_websocket = MagicMock()
_mock_websocket.manager = MagicMock()
_mock_websocket.manager.broadcast_event = AsyncMock()
_mock_psm = MagicMock()
_mock_psm.register_strategy = AsyncMock()
_mock_psm.unregister_strategy = MagicMock()
_mock_websocket.price_stream_manager = _mock_psm
sys.modules["app.services.websocket"] = _mock_websocket


from app.schemas.bot import StrategyConfig  # noqa: E402


def make_bot_config(**overrides):
    """Bot config exactly as the API stores it when a bot is created: every
    StrategyConfig field present and validated, not a partial dict that
    silently relies on code-side .get() defaults (that's how
    sl_breakeven_plus went unnoticed by the breakeven tests)."""
    return StrategyConfig(**{**_BASE_FIELDS, **overrides}).model_dump()


_BASE_FIELDS = {
    "entry_size_usdt": 100,
    "pyramiding_multiplier": 1.5,
    "order_count": 3,
    "step_percent": 2.0,
    "sl_initial": 3.0,
    "sl_after_order3": 1.0,
    "use_trailing": False,
    "trailing_percent": 1.5,
    "leverage": 10,
}

BASE_CONFIG = make_bot_config()


def make_mock_bot(config=None, side="LONG", symbol="BTCUSDT", state="IDLE"):
    bot = MagicMock()
    bot.id = 1
    bot.symbol = symbol
    bot.side = side
    bot.state = state
    bot.config = config or dict(BASE_CONFIG)
    bot.total_pnl = 0.0
    bot.started_at = None
    bot.stopped_at = None
    return bot


def make_mock_position(bot_id=1, symbol="BTCUSDT", side="LONG",
                       average_price=50000.0, total_size=100.0,
                       current_sl=48500.0, order_count=1):
    pos = MagicMock()
    pos.id = 1
    pos.bot_id = bot_id
    pos.symbol = symbol
    pos.side = side
    pos.average_price = average_price
    pos.total_size = total_size
    pos.current_sl = current_sl
    pos.order_count = order_count
    pos.is_open = True
    pos.is_bot_managed = True
    pos.trailing_enabled = True
    pos.unrealized_pnl = 0.0
    pos.opened_at = None
    pos.closed_at = None
    pos.realized_pnl = None
    return pos


def make_mock_db(bot, position=None):
    """Create async mock DB session that returns bot and position on execute()."""
    db = AsyncMock()

    # Track added objects
    db._added = []

    def side_effect_add(obj):
        db._added.append(obj)

    db.add = MagicMock(side_effect=side_effect_add)

    # execute() returns different scalars depending on call order
    call_count = {"n": 0}
    results = [bot, position]

    async def execute_side_effect(query, *args, **kwargs):
        result = AsyncMock()
        idx = call_count["n"]
        call_count["n"] += 1

        if idx < len(results):
            obj = results[idx]
        else:
            obj = None

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = obj
        scalar_result.scalars.return_value.all.return_value = []
        return scalar_result

    db.execute = execute_side_effect
    return db
