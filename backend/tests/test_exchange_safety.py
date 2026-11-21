"""Страховки исполнения: неподтверждённое закрытие, сирота на бирже, очередь цен у каждого бота."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.paper_executor import PaperExecutorAdapter
from app.application.trading.close_position import ClosePositionUseCase
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from app.models import Trade
from app.services import exchange_issues
from app.services.exchange_watch import groups_to_check
from app.services.strategy import BotState, StrategyEngine
from tests.conftest import make_mock_bot

# conftest подменяет app.services.websocket моком — грузим настоящий модуль из файла
_spec = importlib.util.spec_from_file_location(
    "real_websocket_workers", Path(__file__).parent.parent / "app" / "services" / "websocket.py")
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)


@pytest.fixture(autouse=True)
def _clean_issues():
    exchange_issues.reset()
    yield
    exchange_issues.reset()


def _db():
    db = AsyncMock()
    db._added = []
    db.add = MagicMock(side_effect=db._added.append)
    return db


def _executor(close_ok: bool, can_verify: bool):
    ex = MagicMock()
    ex.can_verify = can_verify
    ex.close_position = AsyncMock(return_value={"success": close_ok, "error": "осталось 5"})
    ex.fee_rate = None
    return ex


def _position():
    return MagicMock(average_price=100.0, total_size=100.0, order_count=1, opened_at=None)


def _calc(bot):
    calc = PositionCalculator(bot.config)
    calc.add_order(OrderInfo(1, 100.0, 100.0))
    return calc


def _publisher():
    p = MagicMock()
    p.publish = AsyncMock()
    return p


# --- закрытие ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_unconfirmed_close_keeps_position_open():
    """Биржа видна и говорит «позиция открыта» — закрыть только у себя значит бросить её без стопа."""
    bot, pos, db = make_mock_bot(), _position(), _db()
    res = await ClosePositionUseCase(_executor(False, True), _publisher()).execute(
        bot, pos, _calc(bot), 97.0, "SL_HIT", db)
    assert res["success"] is False
    assert not any(isinstance(o, Trade) for o in db._added)
    assert pos.is_open is not False
    assert any("не закрылась на бирже" in i for i in exchange_issues.issues_for(bot.id))


@pytest.mark.asyncio
async def test_blind_executor_closes_locally_and_raises_issue():
    """Cryptorg без ключа: проверить нечем — сделка закрывается у нас, но это видно в health."""
    bot, pos, db = make_mock_bot(), _position(), _db()
    res = await ClosePositionUseCase(_executor(False, False), _publisher()).execute(
        bot, pos, _calc(bot), 97.0, "SL_HIT", db)
    assert res["success"] is True
    assert any(isinstance(o, Trade) for o in db._added)
    assert any("проверь позицию в Cryptorg" in i for i in exchange_issues.issues_for(bot.id))


@pytest.mark.asyncio
async def test_confirmed_close_clears_previous_close_issue():
    bot = make_mock_bot()
    exchange_issues.report(bot.id, "close", "не закрылась")
    await ClosePositionUseCase(_executor(True, True), _publisher()).execute(
        bot, _position(), _calc(bot), 97.0, "SL_HIT", _db())
    assert exchange_issues.issues_for(bot.id) == []


def _engine(bot, close_results):
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.bot_id, engine._fixed_db, engine.bot = bot.id, _db(), bot
    engine.position = MagicMock(is_open=True, is_bot_managed=True, average_price=100.0,
                                current_sl=98.0, unrealized_pnl=0.0, trailing_enabled=False)
    engine.current_state = BotState.PYRAMIDING
    engine._is_adding_order = engine._is_closing = engine._is_entering = False
    engine._last_tick_log = 0.0
    engine._last_reconcile = 1e18  # сверку не трогаем
    engine._executor = MagicMock()
    engine._publisher = _publisher()
    engine.calculator = _calc(bot)
    engine._close_uc = MagicMock()
    engine._close_uc.execute = AsyncMock(side_effect=close_results)
    engine._price_update_uc = MagicMock()
    engine._price_update_uc.execute = AsyncMock()
    return engine


@pytest.mark.asyncio
async def test_engine_retries_failed_close_even_if_price_recovers(monkeypatch):
    bot = make_mock_bot()  # LONG, стоп 98
    engine = _engine(bot, [{"success": False, "error": "x"}, {"success": True}])
    clock = [1000.0]
    monkeypatch.setattr("app.services.strategy.time.time", lambda: clock[0])

    await engine.on_price_update(97.0)  # стоп → закрытие не подтвердилось
    assert engine._pending_close == "SL_HIT" and engine.position is not None

    clock[0] += 5
    await engine.on_price_update(101.0)  # пауза перед повтором: ничего не делаем
    assert engine._close_uc.execute.await_count == 1
    engine._price_update_uc.execute.assert_not_awaited()

    clock[0] += 20
    await engine.on_price_update(101.0)  # цена вернулась, но выход уже решён — повторяем
    assert engine._close_uc.execute.await_count == 2
    assert engine._close_uc.execute.await_args.args[4] == "SL_HIT"
    assert engine._pending_close is None and engine.position is None


@pytest.mark.asyncio
async def test_bybit_close_of_already_closed_position_is_success():
    from app.adapters.bybit_executor import BybitExecutorAdapter
    ex = BybitExecutorAdapter.__new__(BybitExecutorAdapter)
    ex.get_position = AsyncMock(return_value=(0.0, 0.0))
    assert (await ex.close_position("SOLUSDT", "LONG"))["success"] is True
    ex.get_position = AsyncMock(return_value=None)
    assert (await ex.close_position("SOLUSDT", "LONG"))["success"] is False


# --- сирота -----------------------------------------------------------------

def _bot(id, exchange="cryptorg", account=1, symbol="SOLUSDT", side="SHORT", state="SIGNAL", **cfg):
    return SimpleNamespace(id=id, exchange=exchange, account_id=account, bybit_account_id=account,
                           symbol=symbol, side=side, state=state, config=cfg)


def test_orphan_groups_skip_paper_straddle_and_busy_groups():
    bots = [
        _bot(1), _bot(2),                                  # одна группа, обе ждут сигнал
        _bot(3, symbol="ETHUSDT"), _bot(4, symbol="ETHUSDT", state="PYRAMIDING"),  # занята ботом 4
        _bot(5, exchange="paper"),
        _bot(6, symbol="BTCUSDT", bot_type="straddle"),
        _bot(7, exchange="bybit", symbol="XRPUSDT"),
    ]
    groups = groups_to_check(bots, open_bot_ids={4})
    assert {k: [b.id for b in v] for k, v in groups.items()} == {
        ("cryptorg", 1, "SOLUSDT", "SHORT"): [1, 2],
        ("bybit", 1, "XRPUSDT", "SHORT"): [7],
    }


@pytest.mark.asyncio
async def test_orphan_reported_only_on_second_sighting(monkeypatch):
    from app.services import exchange_watch as mod

    bot = _bot(1)
    result = MagicMock()
    result.scalars.return_value.all.side_effect = [[bot], [], [bot], [], [bot], []]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(mod, "AsyncSessionLocal", MagicMock(return_value=session))
    sizes = iter([2.5, 2.5, 0.0])
    executor = MagicMock()
    executor.get_open_position_size = AsyncMock(side_effect=lambda *a: next(sizes))
    monkeypatch.setattr("app.adapters.executor_factory.build_executor", AsyncMock(return_value=executor))

    watch = mod.ExchangeWatch()
    assert await watch.check_once() == 0 and exchange_issues.issues_for(1) == []  # вход мог быть в пути
    assert await watch.check_once() == 1
    assert "её никто не ведёт" in exchange_issues.issues_for(1)[0]
    assert await watch.check_once() == 0 and exchange_issues.issues_for(1) == []  # позиция ушла


# --- очередь цен у каждого бота -------------------------------------------------

class SlowEngine:
    def __init__(self, symbol, delay):
        self.bot = SimpleNamespace(symbol=symbol)
        self.delay = delay
        self.seen = []

    async def on_price_update(self, price):
        self.seen.append(price)
        await asyncio.sleep(self.delay)


@pytest.mark.asyncio
async def test_slow_bot_does_not_delay_others_and_gets_latest_price():
    psm = ws.PriceStreamManager()
    slow, fast = SlowEngine("SOLUSDT", 0.3), SlowEngine("SOLUSDT", 0)
    for bot_id, engine in ((1, slow), (2, fast)):
        psm.strategy_engines[bot_id] = engine
        psm.workers[bot_id] = ws.EngineWorker(bot_id, engine)
        psm.registered_bots.add(bot_id)

    for price in (1.0, 2.0, 3.0):
        await psm._update_strategies("SOLUSDT", price)
        await asyncio.sleep(0.02)
    assert fast.seen == [1.0, 2.0, 3.0]  # быстрый не ждал медленного
    assert slow.seen == [1.0]            # медленный ещё занят первым тиком

    await asyncio.sleep(0.4)
    assert slow.seen == [1.0, 3.0]       # промежуточная 2.0 заменена последней
    await psm.stop()


@pytest.mark.asyncio
async def test_worker_stopping_itself_finishes_current_tick():
    """Бот закрыл позицию и снимает себя из своей же задачи — операция не должна оборваться."""
    finished = []

    class SelfStopping:
        bot = SimpleNamespace(symbol="SOLUSDT")

        async def on_price_update(self, price):
            worker.stop()
            await asyncio.sleep(0.01)  # «запись в базу» после снятия
            finished.append(price)

    worker = ws.EngineWorker(1, SelfStopping())
    worker.push(1.0)
    await asyncio.sleep(0.05)
    assert finished == [1.0] and worker.task.done() and not worker.task.cancelled()
