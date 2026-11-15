import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.strategy import StrategyEngine, BotState
from app.domain.trading.position_calculator import PositionCalculator
from app.domain.trading.entities import OrderInfo
from app.application.trading.open_position import OpenPositionUseCase
from app.application.trading.close_position import ClosePositionUseCase
from app.application.trading.add_pyramiding_order import AddPyramidingOrderUseCase
from app.application.trading.handle_price_update import HandlePriceUpdateUseCase
from tests.conftest import BASE_CONFIG, make_bot_config, make_mock_bot, make_mock_position


ENTRY_PRICE = 50000.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_engine(bot, position, db):
    """Build a StrategyEngine with mocked executor/market_data/publisher,
    wired through the real use-case classes — mirrors what initialize()
    does, without touching the DB or a real Cryptorg account.
    """
    executor = MagicMock()
    executor.open_position = AsyncMock(return_value={"success": True, "orderId": "ord_1"})
    executor.add_to_position = AsyncMock(return_value={"success": True, "orderId": "ord_2"})
    executor.close_position = AsyncMock(return_value={"success": True})
    executor.update_stop_and_tp = AsyncMock(return_value={"success": True})

    market_data = MagicMock()
    market_data.get_ticker = AsyncMock(return_value={"lastPrice": str(ENTRY_PRICE)})

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    engine = StrategyEngine.__new__(StrategyEngine)
    engine.bot_id = bot.id
    engine.db = db
    engine.bot = bot
    engine.position = position
    engine.current_state = BotState(bot.state) if isinstance(bot.state, str) else bot.state
    engine._is_adding_order = False
    engine._is_closing = False
    engine._is_entering = False
    engine._last_tick_log = 0.0
    engine._market = market_data
    engine._publisher = publisher
    engine._executor = executor
    engine._last_reconcile = time.time()

    engine._open_uc = OpenPositionUseCase(executor, market_data, publisher)
    engine._close_uc = ClosePositionUseCase(executor, publisher)
    engine._add_order_uc = AddPyramidingOrderUseCase(executor, market_data, publisher)
    engine._price_update_uc = HandlePriceUpdateUseCase(publisher)

    engine.calculator = PositionCalculator(bot.config)

    return engine, executor, market_data, publisher


def _make_engine_after_entry(config=None):
    """Return StrategyEngine in PYRAMIDING state with 1 order at 50000."""
    cfg = make_bot_config(**(config or {}))

    bot = make_mock_bot(config=cfg, state="PYRAMIDING")

    pos = make_mock_position(
        average_price=ENTRY_PRICE,
        total_size=100.0,
        current_sl=ENTRY_PRICE * (1 - cfg["sl_initial"] / 100),  # 48500
        order_count=1,
    )
    pos.is_bot_managed = True
    pos.trailing_enabled = True

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    engine, executor, market_data, publisher = _make_engine(bot, pos, db)
    engine.calculator.add_order(OrderInfo(1, ENTRY_PRICE, 100.0))

    return engine, bot, pos, db, executor


def _published_events(publisher):
    return [c.args[0] for c in publisher.publish.call_args_list]


# ── Сценарий 1: manual_entry → создаёт позицию + выставляет SL ───────────────

@pytest.mark.asyncio
async def test_manual_entry_creates_position_and_sets_sl():
    cfg = dict(BASE_CONFIG)
    bot = make_mock_bot(config=cfg, state="IDLE")

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    engine, executor, market_data, publisher = _make_engine(bot, None, db)

    result = await engine.manual_entry()

    assert result["success"] is True, result
    assert result["price"] == ENTRY_PRICE
    assert result["size"] == 100.0
    # SL = 50000 * (1 - 0.03) = 48500
    assert result["sl"] == pytest.approx(48500.0)
    assert engine.current_state == BotState.PYRAMIDING

    market_data.get_ticker.assert_called_once_with("BTCUSDT")
    executor.open_position.assert_called_once()
    open_kwargs = executor.open_position.call_args.kwargs
    assert open_kwargs["sl_percent"] == pytest.approx(3.0)


# ── Сценарий 2: on_price_update — цена у entry, SL не двигается ──────────────

@pytest.mark.asyncio
async def test_price_update_no_sl_movement_at_entry_price():
    engine, bot, pos, db, executor = _make_engine_after_entry()
    initial_sl = pos.current_sl

    await engine.on_price_update(ENTRY_PRICE)

    assert pos.current_sl == pytest.approx(initial_sl)
    executor.update_stop_and_tp.assert_not_called()


# ── Сценарий 3: trailing SL двигается при росте цены (LONG) ──────────────────

@pytest.mark.asyncio
async def test_trailing_sl_moves_on_price_increase():
    # order_count=2 means max orders reached, so no more pyramiding → trailing activates.
    # tp_percent=100 (no take-profit): with the real default tp 3% the bot would
    # close at 52118 long before price reaches 55000, and trailing never runs.
    engine, bot, pos, db, executor = _make_engine_after_entry(
        config={"use_trailing": True, "trailing_percent": 1.5, "order_count": 2, "tp_percent": 100}
    )
    # Add 2nd order so we have max orders and trailing can activate
    engine.calculator.add_order(OrderInfo(2, 51000.0, 150.0))
    pos.order_count = 2
    pos.total_size = 250.0
    pos.average_price = engine.calculator.calculate_average_price(engine.calculator.orders)
    # order 2 moved SL to breakeven + sl_breakeven_plus
    pos.current_sl = pos.average_price * (1 + engine.calculator.config["sl_breakeven_plus"] / 100)

    high_price = 55000.0
    # trailing_sl = 55000*(1-0.015) = 54175

    await engine.on_price_update(high_price)

    expected_trailing_sl = high_price * (1 - 0.015)
    assert pos.current_sl == pytest.approx(expected_trailing_sl)


# ── Сценарий 4: пирамидинг — добавляется ордер при достижении step_percent ───

@pytest.mark.asyncio
async def test_pyramiding_order_added_on_step():
    engine, bot, pos, db, executor = _make_engine_after_entry()
    pyramid_price = ENTRY_PRICE * (1 + BASE_CONFIG["step_percent"] / 100)  # 51000
    market_data_ticker = {"lastPrice": str(pyramid_price)}
    engine._market.get_ticker = AsyncMock(return_value=market_data_ticker)

    await engine.on_price_update(pyramid_price)

    assert len(engine.calculator.orders) == 2
    assert pos.order_count == 2
    # second order size: 100 * 1.5 = 150
    assert engine.calculator.orders[1].size == pytest.approx(150.0)

    # avg = (50000*100 + 51000*150) / 250 = 50600
    expected_avg = (50000 * 100 + pyramid_price * 150) / 250
    assert pos.average_price == pytest.approx(expected_avg)

    executor.add_to_position.assert_called_once()
    executor.update_stop_and_tp.assert_called_once()


# ── Сценарий 5: SL сработал → позиция закрыта ────────────────────────────────

@pytest.mark.asyncio
async def test_sl_hit_closes_position():
    engine, bot, pos, db, executor = _make_engine_after_entry()
    below_sl = pos.current_sl - 100  # 48400, below SL 48500

    await engine.on_price_update(below_sl)

    assert bot.state == "IDLE"
    assert engine.current_state == BotState.IDLE
    executor.close_position.assert_called_once()


# ── Сценарий 6: is_bot_managed=False — движок не трогает позицию ─────────────

@pytest.mark.asyncio
async def test_manual_control_position_untouched():
    engine, bot, pos, db, executor = _make_engine_after_entry()
    pos.is_bot_managed = False
    below_sl = pos.current_sl - 100  # would trigger SL if bot-managed

    await engine.on_price_update(below_sl)

    assert engine.current_state == BotState.PYRAMIDING  # unchanged
    executor.close_position.assert_not_called()
    executor.add_to_position.assert_not_called()
    executor.update_stop_and_tp.assert_not_called()


# ── Сценарий 7: trailing_enabled=False — SL не двигается тиками ──────────────

@pytest.mark.asyncio
async def test_trailing_disabled_sl_stays_pinned():
    # tp_percent=100: otherwise the default 3% TP closes the position at 55000
    # and the assertion below would pass for the wrong reason.
    engine, bot, pos, db, executor = _make_engine_after_entry(
        config={"use_trailing": True, "trailing_percent": 1.5, "order_count": 2, "tp_percent": 100}
    )
    engine.calculator.add_order(OrderInfo(2, 51000.0, 150.0))
    pos.order_count = 2
    pos.total_size = 250.0
    pos.average_price = engine.calculator.calculate_average_price(engine.calculator.orders)
    # order 2 already moved SL to breakeven + sl_breakeven_plus
    breakeven_sl = pos.average_price * (1 + engine.calculator.config["sl_breakeven_plus"] / 100)
    pos.current_sl = breakeven_sl
    pos.trailing_enabled = False

    high_price = 55000.0  # would normally pull trailing SL up to 54175

    await engine.on_price_update(high_price)

    # trailing_enabled=False means calculate_stop_loss falls through to
    # dynamic_sl (breakeven + plus), which equals the existing SL — so
    # current_sl stays exactly where it was instead of trailing to 54175.
    assert pos.current_sl == pytest.approx(breakeven_sl)
