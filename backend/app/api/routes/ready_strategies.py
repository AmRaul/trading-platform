from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.core.database import get_db
from app.models import User, Bot
from app.api.deps import get_current_user
from app.api.routes.bots import validate_bot_accounts
from app.domain.ready_strategies.catalog import ReadyStrategy, list_strategies, get_strategy
from app.schemas.bot import StrategyConfig, BotResponse
from app.schemas.ready_strategy import ReadyStrategyListItem, ReadyStrategyDetail, LaunchRequest

router = APIRouter()


def _base(s: ReadyStrategy) -> dict:
    return {
        "slug": s.slug,
        "name": s.name,
        "summary": s.summary,
        "symbol": s.symbol,
        "side": s.side,
        "timeframe": s.timeframe,
        "launch_available": s.launch_available,
    }


@router.get("/", response_model=List[ReadyStrategyListItem])
async def get_ready_strategies(current_user: User = Depends(get_current_user)):
    return [
        {**_base(s), "variants": [
            {"key": v.key, "name": v.name, "metrics": v.backtest()["metrics"]} for v in s.variants
        ]}
        for s in list_strategies()
    ]


@router.get("/{slug}", response_model=ReadyStrategyDetail)
async def get_ready_strategy(slug: str, current_user: User = Depends(get_current_user)):
    s = get_strategy(slug)
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {
        **_base(s),
        "description": s.description,
        "entry_rules": s.entry_rules,
        "exit_rules": s.exit_rules,
        "risk_notes": s.risk_notes,
        "backtest_assumptions": s.backtest_assumptions,
        "launch_blockers": s.launch_blockers,
        "variants": [
            {
                "key": v.key,
                "name": v.name,
                "description": v.description,
                "first_order_pct_of_deposit": v.first_order_pct_of_deposit,
                "bot_preset": s.variant_preset(v),
                "backtest": v.backtest(),
            }
            for v in s.variants
        ],
    }


@router.post("/{slug}/launch", response_model=BotResponse)
async def launch_ready_strategy(
    slug: str,
    request: LaunchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Запуск в один клик: создаёт бота из пресета варианта и сразу ставит его
    в ожидание сигнала входа (state SIGNAL)."""
    s = get_strategy(slug)
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if not s.launch_available:
        raise HTTPException(status_code=400, detail="; ".join(s.launch_blockers))
    variant = next((v for v in s.variants if v.key == request.variant_key), None)
    if not variant:
        raise HTTPException(status_code=404, detail="Variant not found")

    await validate_bot_accounts(
        db, current_user, request.exchange, request.account_id, request.bybit_account_id
    )
    if request.exchange == "cryptorg" and request.account_id is None:
        raise HTTPException(status_code=400, detail="exchange=cryptorg requires account_id")

    entry_size = round(request.deposit_usdt * variant.first_order_pct_of_deposit / 100, 2)
    try:
        config = StrategyConfig(**{**s.variant_preset(variant), "entry_size_usdt": entry_size})
    except ValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Первый ордер {entry_size} USDT вне допустимых границ: "
                   + "; ".join(err["msg"] for err in e.errors()),
        )

    bot = Bot(
        user_id=current_user.id,
        exchange=request.exchange,
        account_id=request.account_id if request.exchange == "cryptorg" else None,
        bybit_account_id=request.bybit_account_id if request.exchange == "bybit" else None,
        name=f"{s.name} · {variant.name}",
        symbol=s.symbol,
        side=s.side,
        config=config.model_dump(),
        state="SIGNAL",
        is_active=False,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot
