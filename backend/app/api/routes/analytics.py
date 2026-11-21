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
