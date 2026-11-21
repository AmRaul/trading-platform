"""
Эндпоинты для анализа (их вызывает MCP-сервер services/mcp): рыночный контекст,
проверка «живы ли боты», сделки за период и журнал разборов. Только чтение,
кроме записи в журнал; торговых действий здесь нет.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bybit_market_data import BybitMarketDataAdapter
from app.api.deps import get_current_user
from app.application.monitoring.bots_health import assess_bot
from app.application.monitoring.reconcile_position import ReconcilePositionUseCase
from app.core.database import get_db
from app.domain.market.context import build_market_context
from app.models import Bot, Order, Position, Review, Trade, User
from app.schemas.trade import TradeResponse

logger = logging.getLogger(__name__)
router = APIRouter()

TIMEFRAMES = {"15m": "15", "15": "15", "1h": "60", "60": "60", "4h": "240", "240": "240",
              "1d": "D", "d": "D", "D": "D", "1w": "W", "w": "W", "W": "W"}
# Индикаторам нужна история сверх показанного окна: EMA200 — минимум ~400 свечей
HISTORY = 500


@router.get("/market-context")
async def market_context(
    symbol: str = Query(..., min_length=3, max_length=20),
    timeframe: str = Query("1d"),
    bars: int = Query(30, ge=5, le=200),
    current_user: User = Depends(get_current_user),
):
    tf = TIMEFRAMES.get(timeframe)
    if not tf:
        raise HTTPException(status_code=400, detail=f"timeframe: один из {sorted(set(TIMEFRAMES))}")
    symbol = symbol.upper()
    market = BybitMarketDataAdapter()
    candles = await market.get_klines(symbol, tf, HISTORY)
    if not candles:
        raise HTTPException(status_code=404, detail=f"Нет свечей Bybit для {symbol}")
    ctx = build_market_context(candles, tf, bars)
    ctx["symbol"] = symbol
    ctx["derivatives"] = await _derivatives(symbol)
    return ctx


async def _derivatives(symbol: str) -> Dict[str, Any]:
    """Funding и open interest Bybit linear (публичные данные)."""
    from app.services.bybit import bybit_client
    out: Dict[str, Any] = {}
    loop = asyncio.get_event_loop()
    try:
        t = await loop.run_in_executor(
            None, lambda: bybit_client.http_client.get_tickers(category="linear", symbol=symbol))
        row = (t.get("result", {}).get("list") or [{}])[0]
        if row.get("fundingRate") not in (None, ""):
            out["funding_rate_pct"] = round(float(row["fundingRate"]) * 100, 4)
        if row.get("openInterestValue"):
            out["open_interest_usd"] = round(float(row["openInterestValue"]))
        if row.get("price24hPcnt"):
            out["change_24h_pct"] = round(float(row["price24hPcnt"]) * 100, 2)
    except Exception as e:
        logger.warning(f"[analytics] tickers {symbol}: {e}")
    try:
        oi = await loop.run_in_executor(None, lambda: bybit_client.http_client.get_open_interest(
            category="linear", symbol=symbol, intervalTime="1d", limit=8))
        rows = oi.get("result", {}).get("list") or []
        if len(rows) >= 2:  # от новой к старой
            new, old = float(rows[0]["openInterest"]), float(rows[-1]["openInterest"])
            out["open_interest_change_7d_pct"] = round((new / old - 1) * 100, 2) if old else None
    except Exception as e:
        logger.warning(f"[analytics] open interest {symbol}: {e}")
    return out


@router.get("/bots-health")
async def bots_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.signal_scheduler import signal_scheduler
    from app.services.websocket import price_stream_manager

    bots = (await db.execute(
        select(Bot).where(Bot.user_id == current_user.id).order_by(Bot.id))).scalars().all()
    open_ids = set()
    if bots:
        open_ids = set((await db.execute(select(Position.bot_id).where(and_(
            Position.bot_id.in_([b.id for b in bots]), Position.is_open == True)))).scalars().all())  # noqa: E712

    from app.models.cryptorg_account import CryptorgAccount
    from app.services import exchange_issues
    # аккаунты Cryptorg, у которых есть ключ Bybit для сверки — остальные боты работают вслепую
    seeing = set((await db.execute(select(CryptorgAccount.id).where(and_(
        CryptorgAccount.user_id == current_user.id,
        CryptorgAccount.api_key.isnot(None), CryptorgAccount.api_secret.isnot(None))))).scalars().all())

    now_ms = int(time.time() * 1000)
    rows = []
    for b in bots:
        # Проверка сигнала нужна только ждущему сигнал боту; у остальных она старая и сбивает с толку
        last = signal_scheduler.last_result.get(b.id) if b.state == "SIGNAL" else None
        tick = price_stream_manager.last_tick_ms.get(b.symbol)
        health = assess_bot(
            state=b.state, config=b.config or {}, has_open_position=b.id in open_ids,
            registered_for_prices=b.id in price_stream_manager.registered_bots,
            scheduler_running=signal_scheduler.running, scheduler_started_ms=signal_scheduler.started_ms,
            last_check=last, now_ms=now_ms, last_tick_ms=tick,
        )
        # проблемы исполнения: биржа не подтвердила ордер, позиция-сирота (services/exchange_issues)
        exec_issues = exchange_issues.issues_for(b.id)
        if exec_issues:
            health = {**health, "status": "problem", "issues": [*health.get("issues", []), *exec_issues]}
        if b.exchange == "cryptorg" and b.account_id not in seeing:
            health = {**health, "notes": [*health.get("notes", []),
                                          "Cryptorg без ключа Bybit: исполнение ордеров не проверяется"]}
        rows.append({
            "bot_id": b.id, "name": b.name, "symbol": b.symbol, "side": b.side,
            "exchange": b.exchange, "state": b.state, "has_open_position": b.id in open_ids,
            "last_signal_check": {**last, "minutes_ago": (now_ms - last["checked_at_ms"]) // 60_000} if last else None,
            "last_price_tick_sec_ago": (now_ms - tick) // 1000 if tick and b.state != "SIGNAL" else None,
            **health,
        })
    return {
        "scheduler_running": signal_scheduler.running,
        "problems": sum(r["status"] == "problem" for r in rows),
        "bots": rows,
    }


@router.get("/forward-test")
async def forward_test(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Комплекты бумажного форвард-теста: ожидания, критерии остановки и боты каждой части
    (по полю bot.forward_test, не по названию — переименование разбор не ломает)."""
    from app.domain.forward_test import FORWARD_TEST_SETS, parse

    bots = (await db.execute(select(Bot).where(and_(
        Bot.user_id == current_user.id, Bot.forward_test.isnot(None))).order_by(Bot.id))).scalars().all()
    members: Dict[str, Dict[str, List[Dict]]] = {}
    for b in bots:
        key = parse(b.forward_test)
        if key:
            members.setdefault(key[0], {}).setdefault(key[1], []).append(
                {"bot_id": b.id, "name": b.name, "symbol": b.symbol, "state": b.state})
    sets = {}
    for key, s in FORWARD_TEST_SETS.items():
        sets[key] = {**s, "parts": {
            part: {**p, "bots": members.get(key, {}).get(part, [])} for part, p in s["parts"].items()}}
    return {"sets": sets}


@router.get("/reconcile/{position_id}")
async def reconcile_position(
    position_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сверка позиции с бэктестом на тех же свечах: сигнал входа, доборы, выход."""
    position = await db.get(Position, position_id)
    bot = await db.get(Bot, position.bot_id) if position else None
    if not bot or bot.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Позиция не найдена")
    orders = (await db.execute(select(Order).where(Order.position_id == position_id))).scalars().all()
    trade = (await db.execute(select(Trade).where(Trade.position_id == position_id))).scalars().first()
    return await ReconcilePositionUseCase(BybitMarketDataAdapter()).execute(
        bot=bot, position=position, orders=orders, trade=trade)


@router.get("/trades", response_model=List[TradeResponse])
async def trades(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    bot_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Все сделки за период (без лимита в 100, как у /api/trades) — для разборов."""
    q = select(Trade).join(Bot, Bot.id == Trade.bot_id).where(Bot.user_id == current_user.id)
    if since:
        q = q.where(Trade.closed_at >= since)
    if until:
        q = q.where(Trade.closed_at < until)
    if bot_id is not None:
        q = q.where(Trade.bot_id == bot_id)
    return (await db.execute(q.order_by(Trade.closed_at).limit(10_000))).scalars().all()


@router.get("/position-levels/{bot_id}")
async def position_levels(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Уровни открытой позиции бота, посчитанные логикой самого бота: стоп и результат
    на нём с комиссией, тейк, с какой цены трейлинг двинет стоп, следующий ордер и стоп после него."""
    from app.application.monitoring.position_levels import DEFAULT_FEE_RATE, position_levels as levels
    from app.core.redis import get_position_state
    from app.domain.trading.entities import OrderInfo

    bot = (await db.execute(select(Bot).where(Bot.id == bot_id, Bot.user_id == current_user.id))).scalar_one_or_none()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    pos = (await db.execute(select(Position).where(and_(
        Position.bot_id == bot_id, Position.is_open == True)))).scalar_one_or_none()  # noqa: E712
    if not pos:
        return {"bot_id": bot_id, "open_position": None}
    orders = (await db.execute(select(Order).where(Order.position_id == pos.id)
                               .order_by(Order.order_number))).scalars().all()
    live = await get_position_state(str(bot_id)) or {}
    ticker = await BybitMarketDataAdapter().get_ticker(bot.symbol)
    if not ticker or not ticker.get("lastPrice"):
        raise HTTPException(status_code=502, detail="Нет цены с Bybit")
    return {
        "bot_id": bot_id, "position_id": pos.id, "side": bot.side,
        **levels(
            bot.config or {}, bot.side, [OrderInfo(o.order_number, o.price, o.size) for o in orders],
            live.get("current_sl", pos.current_sl), float(ticker["lastPrice"]),
            live.get("total_size", pos.total_size), trailing_enabled=pos.trailing_enabled,
            fee_rate=DEFAULT_FEE_RATE,
        ),
    }


SNAPSHOTS_KEEP = 500  # снимков what_changed на пользователя


@router.get("/changes")
async def changes(
    since: Optional[datetime] = None,
    save: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Что изменилось с прошлой проверки (или с since): входы, доборы, закрытые сделки,
    новые/удалённые боты, смена состояния, сдвиги стопов, изменение плавающего PnL.

    База сравнения — последний снимок не позже since (без since — просто последний).
    save=True — записать текущее состояние новым снимком: следующий вызов покажет
    изменения уже от этой проверки. Снимков нет (первый вызов) — только события за 24 ч."""
    from datetime import timedelta, timezone

    from app.application.monitoring.what_changed import bot_snapshot, diff
    from app.core.redis import get_position_state
    from app.models import StateSnapshot

    now = datetime.now(timezone.utc)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    bots = (await db.execute(select(Bot).where(Bot.user_id == current_user.id).order_by(Bot.id))).scalars().all()
    names = {b.id: b.name for b in bots}
    bot_ids = list(names)
    open_positions = {p.bot_id: p for p in (await db.execute(select(Position).where(and_(
        Position.bot_id.in_(bot_ids), Position.is_open == True)))).scalars().all()} if bot_ids else {}  # noqa: E712
    lives = await asyncio.gather(*[get_position_state(str(bid)) for bid in open_positions])
    live = dict(zip(open_positions, lives))
    current = {str(b.id): bot_snapshot(b, open_positions.get(b.id), live.get(b.id)) for b in bots}

    q = select(StateSnapshot).where(StateSnapshot.user_id == current_user.id)
    if since is not None:
        q = q.where(StateSnapshot.taken_at <= since)
    baseline = (await db.execute(q.order_by(StateSnapshot.taken_at.desc()).limit(1))).scalar_one_or_none()

    start = since or (baseline.taken_at if baseline else now - timedelta(hours=24))
    events: Dict[str, List[Dict]] = {"entries": [], "adds": [], "exits": []}
    if bot_ids:
        for p in (await db.execute(select(Position).where(and_(
                Position.bot_id.in_(bot_ids), Position.opened_at >= start)).order_by(Position.opened_at))).scalars():
            events["entries"].append({"bot_id": p.bot_id, "name": names[p.bot_id], "position_id": p.id,
                                      "at": p.opened_at, "is_open": p.is_open})
        for o in (await db.execute(select(Order).where(and_(
                Order.bot_id.in_(bot_ids), Order.order_number > 1, Order.filled_at >= start))
                .order_by(Order.filled_at))).scalars():
            events["adds"].append({"bot_id": o.bot_id, "name": names[o.bot_id], "order_number": o.order_number,
                                   "price": o.price, "size": o.size, "at": o.filled_at})
        for t in (await db.execute(select(Trade).where(and_(
                Trade.bot_id.in_(bot_ids), Trade.closed_at >= start)).order_by(Trade.closed_at))).scalars():
            events["exits"].append({"bot_id": t.bot_id, "name": names[t.bot_id], "exit_reason": t.exit_reason,
                                    "pnl": round(t.pnl, 2), "exit_price": t.exit_price,
                                    "total_orders": t.total_orders, "at": t.closed_at})

    result: Dict[str, Any] = {
        "since": start,
        "compared_with_snapshot": baseline.taken_at if baseline else None,
        "events": events,
        "realized_in_period": round(sum(e["pnl"] for e in events["exits"]), 2),
    }
    if baseline:
        result.update(diff(baseline.data or {}, current))
    else:
        result["note"] = "снимков ещё не было — показаны только события; сравнение появится со следующего вызова"

    if save:
        db.add(StateSnapshot(user_id=current_user.id, data=current))
        await db.flush()
        old_ids = (await db.execute(select(StateSnapshot.id).where(StateSnapshot.user_id == current_user.id)
                                    .order_by(StateSnapshot.taken_at.desc()).offset(SNAPSHOTS_KEEP))).scalars().all()
        if old_ids:
            from sqlalchemy import delete
            await db.execute(delete(StateSnapshot).where(StateSnapshot.id.in_(old_ids)))
        await db.commit()
    return result


class ReviewCreate(BaseModel):
    kind: str = Field(pattern="^(monthly_review|health_check|second_opinion|note)$")
    summary: str = Field(min_length=1, max_length=20_000)
    bot_id: Optional[int] = None
    position_id: Optional[int] = None
    symbol: Optional[str] = Field(default=None, max_length=20)
    verdict: Optional[Dict[str, Any]] = None


def _review_dict(r: Review, outcome: Optional[Dict] = None) -> Dict:
    return {"id": r.id, "kind": r.kind, "bot_id": r.bot_id, "position_id": r.position_id,
            "symbol": r.symbol, "summary": r.summary, "verdict": r.verdict,
            "created_at": r.created_at, "outcome": outcome}


@router.post("/reviews")
async def create_review(
    data: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if data.bot_id is not None:
        owned = (await db.execute(select(Bot.id).where(
            Bot.id == data.bot_id, Bot.user_id == current_user.id))).scalar_one_or_none()
        if owned is None:
            raise HTTPException(status_code=404, detail="Bot not found")
    review = Review(user_id=current_user.id, **data.model_dump())
    db.add(review)
    await db.commit()
    await db.refresh(review)
    return _review_dict(review)


@router.get("/reviews")
async def list_reviews(
    kind: Optional[str] = None,
    bot_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Журнал от новых к старым. У записей с position_id — исход сделки,
    если позиция уже закрыта: так проверяется, сбылся ли вердикт."""
    q = select(Review).where(Review.user_id == current_user.id)
    if kind:
        q = q.where(Review.kind == kind)
    if bot_id is not None:
        q = q.where(Review.bot_id == bot_id)
    reviews = (await db.execute(q.order_by(Review.created_at.desc()).limit(limit))).scalars().all()

    pos_ids = [r.position_id for r in reviews if r.position_id]
    outcomes: Dict[int, Dict] = {}
    if pos_ids:
        for t in (await db.execute(select(Trade).join(Bot, Bot.id == Trade.bot_id).where(
                Trade.position_id.in_(pos_ids), Bot.user_id == current_user.id))).scalars().all():
            outcomes[t.position_id] = {"exit_reason": t.exit_reason, "exit_price": t.exit_price,
                                       "pnl": t.pnl, "fees": t.fees, "closed_at": t.closed_at}
    return [_review_dict(r, outcomes.get(r.position_id)) for r in reviews]
