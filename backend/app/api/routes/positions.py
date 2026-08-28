from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Sequence
from app.core.database import get_db
from app.core.redis import get_position_state
from app.models import User, Bot, Position, Order
from app.models.cryptorg_account import CryptorgAccount
from app.schemas.position import PositionResponse, PositionManagedUpdate, PositionTrailingUpdate
from app.api.deps import get_current_user
from app.domain.trading.entities import OrderInfo
from app.domain.trading.position_calculator import PositionCalculator
from app.adapters.cryptorg_executor import CryptorgExecutorAdapter
from app.services.cryptorg import get_cryptorg_client
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


async def _apply_live_state(positions: Sequence[Position]) -> Sequence[Position]:
    """Overlay live unrealized_pnl/current_sl from Redis onto open positions.

    handle_price_update.py only writes per-tick PnL/SL to Redis (Postgres
    commits happen on entry/pyramiding/close), so reading straight from the
    DB shows stale — often $0.00 — values for a position that hasn't
    triggered another order yet.
    """
    for pos in positions:
        if not pos.is_open:
            continue
        state = await get_position_state(str(pos.bot_id))
        if not state:
            continue
        if "unrealized_pnl" in state:
            pos.unrealized_pnl = state["unrealized_pnl"]
        if "current_sl" in state:
            pos.current_sl = state["current_sl"]
    return positions


@router.get("/", response_model=List[PositionResponse])
async def get_positions(
    is_open: bool = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = (
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Bot.user_id == current_user.id)
    )
    if is_open is not None:
        query = query.where(Position.is_open == is_open)
    query = query.order_by(Position.opened_at.desc())

    result = await db.execute(query)
    return await _apply_live_state(result.scalars().all())


@router.get("/bot/{bot_id}", response_model=List[PositionResponse])
async def get_bot_positions(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Position.bot_id == bot_id, Bot.user_id == current_user.id)
        .order_by(Position.opened_at.desc())
    )
    return await _apply_live_state(result.scalars().all())


@router.patch("/{position_id}/managed", response_model=PositionResponse)
async def set_position_managed(
    position_id: int,
    data: PositionManagedUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Toggle bot management of a position.

    is_bot_managed=False: the bot stops touching this position entirely
    (no SL checks, no pyramiding, no trailing SL/PnL updates) so the user
    can take over manually — e.g. on the exchange directly. The position
    stays visible here (still is_open) but the bot no longer acts on it.
    """
    result = await db.execute(
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Position.id == position_id, Bot.user_id == current_user.id)
    )
    position = result.scalar_one_or_none()

    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if not position.is_open:
        raise HTTPException(status_code=400, detail="Position is already closed")

    position.is_bot_managed = data.is_bot_managed
    await db.commit()
    await db.refresh(position)

    # If the bot is currently live (registered with the price stream), update
    # the in-memory engine's position too — StrategyEngine holds its own
    # long-lived DB session/object, so a plain DB commit here won't be seen
    # by that session until it's asked to refresh. Single-threaded asyncio
    # event loop, so this is race-free.
    from app.services.websocket import price_stream_manager
    engine = price_stream_manager.strategy_engines.get(position.bot_id)
    if engine and engine.position and engine.position.id == position.id:
        engine.position.is_bot_managed = data.is_bot_managed

    return position


@router.patch("/{position_id}/trailing", response_model=PositionResponse)
async def set_position_trailing(
    position_id: int,
    data: PositionTrailingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enable/disable trailing SL on a position.

    trailing_enabled=False: SL is pinned to the dynamic (sl_after_order3)
    level computed from avg_price — it stops following price ticks. SL-hit
    checks, pyramiding, and TP keep working normally; this only removes the
    trailing component, unlike is_bot_managed=False which stops everything.

    The new SL is pushed to the exchange immediately via update_stop_and_tp
    so the exchange-side stop matches what's shown here right away, instead
    of waiting for the bot to notice on some future price tick.
    """
    result = await db.execute(
        select(Position)
        .join(Bot, Bot.id == Position.bot_id)
        .where(Position.id == position_id, Bot.user_id == current_user.id)
    )
    position = result.scalar_one_or_none()

    if not position:
        raise HTTPException(status_code=404, detail="Position not found")
    if not position.is_open:
        raise HTTPException(status_code=400, detail="Position is already closed")

    bot_result = await db.execute(select(Bot).where(Bot.id == position.bot_id))
    bot = bot_result.scalar_one_or_none()

    order_result = await db.execute(
        select(Order)
        .where(Order.position_id == position.id, Order.status == "FILLED")
        .order_by(Order.order_number)
    )
    orders = order_result.scalars().all()

    calculator = PositionCalculator(bot.config)
    for order in orders:
        calculator.add_order(OrderInfo(order.order_number, order.price, order.size))

    new_sl = position.current_sl

    if not data.trailing_enabled and orders:
        # Re-pin current_sl to the dynamic level right now, rather than
        # waiting for the next price tick — the tick-level "only move if
        # favorable" comparison in handle_price_update.py would otherwise
        # never step DOWN from an already-favorable trailing level.
        current_price = orders[-1].price
        new_sl, _ = calculator.calculate_stop_loss(
            bot.side, calculator.orders, current_price, trailing_enabled=False
        )

        sl_pct = calculator.calculate_sl_percent(position.order_count)
        max_orders = bot.config.get("order_count", 4)
        # Mirror add_pyramiding_order.py: TP only goes live on the exchange
        # once the last pyramiding order has filled — passing tp_percent=None
        # unconditionally here would wrongly clear an already-active TP.
        tp_pct = bot.config.get("tp_percent", 3.0) if position.order_count >= max_orders else None

        account = None
        if bot.account_id:
            acc_result = await db.execute(
                select(CryptorgAccount).where(CryptorgAccount.id == bot.account_id)
            )
            account = acc_result.scalar_one_or_none()
        executor = CryptorgExecutorAdapter(get_cryptorg_client(account))
        update_result = await executor.update_stop_and_tp(
            symbol=bot.symbol,
            side=bot.side.lower(),
            sl_percent=sl_pct,
            tp_percent=tp_pct,
        )
        # Push to the exchange BEFORE touching the DB — if the webhook call
        # fails, we must not report success while the exchange-side stop is
        # still the old trailing one. Fail loudly instead of silently
        # committing a DB state that doesn't match reality.
        if not (update_result and update_result.get("success")):
            logger.error(
                f"Failed to push disabled-trailing SL to exchange for position={position.id}"
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to update stop loss on the exchange — trailing was NOT disabled. Try again."
            )

    position.trailing_enabled = data.trailing_enabled
    position.current_sl = new_sl

    await db.commit()
    await db.refresh(position)

    from app.services.websocket import price_stream_manager
    engine = price_stream_manager.strategy_engines.get(position.bot_id)
    if engine and engine.position and engine.position.id == position.id:
        engine.position.trailing_enabled = data.trailing_enabled
        engine.position.current_sl = position.current_sl

    return position
