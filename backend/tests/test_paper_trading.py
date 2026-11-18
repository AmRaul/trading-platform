"""Бумажная торговля (exchange=paper): реальный движок и use cases,
PaperExecutorAdapter вместо биржи, комиссии вычитаются из PnL сделки."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.executor_factory import build_executor
from app.adapters.paper_executor import PAPER_TAKER_FEE, PaperExecutorAdapter
from app.api.routes.ready_strategies import launch_ready_strategy
from app.application.trading.add_pyramiding_order import AddPyramidingOrderUseCase
from app.application.trading.close_position import ClosePositionUseCase
from app.application.trading.handle_price_update import HandlePriceUpdateUseCase
from app.application.trading.open_position import OpenPositionUseCase
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Trade
from app.ports.exchange_executor import ExchangeExecutor
from app.schemas.bot import BotCreate
from app.schemas.ready_strategy import LaunchRequest
from app.services.strategy import BotState, StrategyEngine
from tests.conftest import BASE_CONFIG, make_mock_bot


def _paper_engine(bot, db, price):
    executor = PaperExecutorAdapter()
    market = MagicMock()
    market.get_ticker = AsyncMock(return_value={"lastPrice": str(price)})
    publisher = MagicMock()
    publisher.publish = AsyncMock()

    engine = StrategyEngine.__new__(StrategyEngine)
    engine.bot_id, engine.db, engine.bot, engine.position = bot.id, db, bot, None
    engine.current_state = BotState.IDLE
    engine._is_adding_order = engine._is_closing = engine._is_entering = False
    engine._last_tick_log = engine._last_reconcile = 0.0
    engine._market, engine._publisher, engine._executor = market, publisher, executor
    engine._open_uc = OpenPositionUseCase(executor, market, publisher)
    engine._close_uc = ClosePositionUseCase(executor, publisher)
    engine._add_order_uc = AddPyramidingOrderUseCase(executor, market, publisher)
    engine._price_update_uc = HandlePriceUpdateUseCase(publisher)
    engine.calculator = PositionCalculator(bot.config)
    return engine


def _db():
    db = AsyncMock()
    db._added = []
    db.add = MagicMock(side_effect=db._added.append)
    return db


def test_paper_executor_satisfies_port():
    assert isinstance(PaperExecutorAdapter(), ExchangeExecutor)


@pytest.mark.asyncio
async def test_paper_executor_never_reconciles():
    assert await PaperExecutorAdapter().get_open_position_size("BTCUSDT", "long") is None


@pytest.mark.asyncio
async def test_factory_builds_paper_executor_without_db():
    bot = make_mock_bot()
    bot.exchange = "paper"
    db = AsyncMock()
    executor = await build_executor(bot, db)
    assert isinstance(executor, PaperExecutorAdapter)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_paper_full_cycle_stop_records_trade_net_of_fees():
    bot = make_mock_bot(config=dict(BASE_CONFIG), state="IDLE")  # 100 USDT, SL 3%
    db = _db()
    engine = _paper_engine(bot, db, 50000.0)

    result = await engine.manual_entry()
    assert result["success"] is True
    assert engine.current_state == BotState.PYRAMIDING
    position = engine.position
    # значения колонок по умолчанию — их проставляет INSERT, а БД здесь мок
    position.is_bot_managed = position.trailing_enabled = True
    position.unrealized_pnl = 0.0

    exit_price = 48400.0  # ниже стопа 48500
    await engine.on_price_update(exit_price)

    trade = next(o for o in db._added if isinstance(o, Trade))
    gross = 100.0 * (exit_price - 50000.0) / 50000.0  # −3.2
    fees = PAPER_TAKER_FEE * 100.0 * (1 + exit_price / 50000.0)
    assert trade.fees == pytest.approx(fees)
    assert trade.pnl == pytest.approx(gross - fees)
    assert bot.total_pnl == pytest.approx(gross - fees)
    assert position.realized_pnl == pytest.approx(gross - fees)
    assert trade.exit_reason == "SL_HIT"
    assert engine.current_state == BotState.IDLE


@pytest.mark.asyncio
async def test_real_exchange_trade_pnl_unchanged():
    """У биржевого исполнителя нет fee_rate — PnL как раньше, fees=None."""
    executor = MagicMock()
    executor.close_position = AsyncMock(return_value={"success": True})
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    bot = make_mock_bot(state="PYRAMIDING")
    calc = PositionCalculator(bot.config)
    from app.domain.trading.entities import OrderInfo
    calc.add_order(OrderInfo(1, 50000.0, 100.0))
    pos = MagicMock(average_price=50000.0, total_size=100.0, order_count=1, opened_at=None)
    db = _db()

    await ClosePositionUseCase(executor, publisher).execute(bot, pos, calc, 51000.0, "TP_HIT", db)

    trade = next(o for o in db._added if isinstance(o, Trade))
    assert trade.fees is None
    assert trade.pnl == pytest.approx(2.0)


def test_bot_create_accepts_paper_without_accounts():
    bot = BotCreate(name="paper", symbol="BTCUSDT", side="LONG", config=BASE_CONFIG, exchange="paper")
    assert bot.exchange == "paper" and bot.account_id is None and bot.bybit_account_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["mrc-dca-btc-15m-long", "alt-short-pyramid-5"])
async def test_launch_ready_strategy_in_paper_mode(slug):
    from app.domain.ready_strategies.catalog import get_strategy
    s = get_strategy(slug)
    req = LaunchRequest(variant_key=s.variants[0].key, deposit_usdt=5700, exchange="paper")
    db = _db()
    user = MagicMock()
    user.id = 7
    await launch_ready_strategy(slug, req, db, user)
    bots = db._added
    assert len(bots) == len(s.launch_legs)
    for b in bots:
        assert b.exchange == "paper" and b.account_id is None and b.bybit_account_id is None
        assert b.state == "SIGNAL"
