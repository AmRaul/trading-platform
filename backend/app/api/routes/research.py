"""Журнал гипотез и прогоны бэктестов (для MCP — проверка идей с телефона).

Считает бэктестер (services/backtester, очередь, 1 ядро), здесь — правила журнала:
гипотеза и критерий до прогона, сначала только обучающий период, отложенный —
один раз после решения, счётчик попыток идеи. Параметры — белый список бэктестера.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.application.research.hypotheses import idea_key, train_view, verdict
from app.core.config import settings
from app.core.database import get_db
from app.models import Hypothesis, User

router = APIRouter()

MAX_RUNNING = 3      # одновременно в работе у пользователя
MAX_PER_DAY = 20     # прогонов в сутки: дёшево гонять с телефона — значит легко подогнать


async def _bt(method: str, path: str, **kw) -> Any:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.request(method, settings.BACKTESTER_URL.rstrip("/") + path, **kw) as r:
                body = await r.json(content_type=None)
                status = r.status
    except (aiohttp.ClientError, TimeoutError) as e:
        raise HTTPException(status_code=502, detail=f"бэктестер недоступен: {type(e).__name__}")
    if status == 400:
        raise HTTPException(status_code=400, detail=(body or {}).get("error", "неверные параметры"))
    if status >= 400:
        raise HTTPException(status_code=502, detail=f"бэктестер ответил {status}")
    return body


@router.get("/bases")
async def bases(_: User = Depends(get_current_user)):
    """Какие стратегии и параметры можно проверять, их значения у живых ботов и пределы."""
    return await _bt("GET", "/api/research/bases")


class HypothesisCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    rationale: Optional[str] = Field(default=None, max_length=5000)
    success_criterion: str = Field(min_length=10, max_length=2000)
    base: str = Field(pattern="^(alt_short|mrc_dca)$")
    changes: Dict[str, Any] = Field(min_length=1)


def _public(h: Hypothesis) -> Dict:
    out = {
        "id": h.id, "title": h.title, "rationale": h.rationale, "success_criterion": h.success_criterion,
        "base": h.base, "changes": h.changes, "attempt": h.attempt, "status": h.status,
        "created_at": h.created_at, "train_decision": h.train_decision, "decision_note": h.decision_note,
    }
    if h.status == "error":
        out["error"] = h.error
    if h.status in ("tested", "revealed") and h.result:
        out["result"] = train_view(h.result, h.attempt)
    if h.status == "revealed":
        out["verdict"] = h.verdict
    return out


@router.post("/hypotheses")
async def create(data: HypothesisCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Записать гипотезу и поставить прогон в очередь. Меняется только то, что в changes."""
    running = (await db.execute(select(func.count(Hypothesis.id)).where(
        Hypothesis.user_id == user.id, Hypothesis.status == "running"))).scalar() or 0
    if running >= MAX_RUNNING:
        raise HTTPException(status_code=429, detail=f"в работе уже {running} гипотезы — дождитесь результата")
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    today = (await db.execute(select(func.count(Hypothesis.id)).where(
        Hypothesis.user_id == user.id, Hypothesis.created_at >= day_ago))).scalar() or 0
    if today >= MAX_PER_DAY:
        raise HTTPException(status_code=429, detail=f"лимит {MAX_PER_DAY} прогонов в сутки — это защита от подгонки")

    key = idea_key(data.base, data.changes)
    attempt = 1 + ((await db.execute(select(func.count(Hypothesis.id)).where(
        Hypothesis.user_id == user.id, Hypothesis.idea_key == key))).scalar() or 0)
    task = await _bt("POST", "/api/research/run", json={"base": data.base, "changes": data.changes})
    h = Hypothesis(user_id=user.id, title=data.title, rationale=data.rationale,
                   success_criterion=data.success_criterion, base=data.base, changes=data.changes,
                   idea_key=key, attempt=attempt, status="running", task_id=task["task_id"])
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return _public(h)


async def _refresh(h: Hypothesis, db: AsyncSession) -> Optional[Dict]:
    """Подтянуть итог из бэктестера, если прогон закончился. Возвращает статус очереди."""
    if h.status != "running":
        return None
    st = await _bt("GET", f"/api/research/status/{h.task_id}")
    if st.get("status") == "completed":
        h.result = await _bt("GET", f"/api/research/result/{h.task_id}")
        h.status = "tested"
        await db.commit()
    elif st.get("status") == "error":
        h.status, h.error = "error", st.get("error")
        await db.commit()
    return st


@router.get("/hypotheses/{hypothesis_id}")
async def get_one(hypothesis_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    h = await db.get(Hypothesis, hypothesis_id)
    if not h or h.user_id != user.id:
        raise HTTPException(status_code=404, detail="Гипотеза не найдена")
    st = await _refresh(h, db)
    out = _public(h)
    if h.status == "running" and st:
        out["progress"] = st.get("progress")
        out["queue_position"] = st.get("queue_position")
    return out


class Reveal(BaseModel):
    train_decision: str = Field(pattern="^(passes|fails)$")
    note: Optional[str] = Field(default=None, max_length=2000)


@router.post("/hypotheses/{hypothesis_id}/reveal")
async def reveal(hypothesis_id: int, data: Reveal, db: AsyncSession = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Решение по обучающему периоду фиксируется, затем — один раз — отложенный период и итог."""
    h = await db.get(Hypothesis, hypothesis_id)
    if not h or h.user_id != user.id:
        raise HTTPException(status_code=404, detail="Гипотеза не найдена")
    await _refresh(h, db)
    if h.status == "revealed":
        raise HTTPException(status_code=409, detail="Отложенный период уже открыт — решение не меняется")
    if h.status != "tested":
        raise HTTPException(status_code=409, detail=f"Прогон не готов (статус {h.status})")
    h.train_decision, h.decision_note = data.train_decision, data.note
    h.verdict = verdict(h.result, data.train_decision, h.attempt)
    h.status, h.revealed_at = "revealed", datetime.now(timezone.utc)
    await db.commit()
    return _public(h)


@router.get("/hypotheses")
async def list_(base: Optional[str] = None, limit: int = Query(30, ge=1, le=200),
                db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Журнал от новых к старым — коротко: что, сколько попыток, чем кончилось."""
    q = select(Hypothesis).where(Hypothesis.user_id == user.id)
    if base:
        q = q.where(Hypothesis.base == base)
    rows = (await db.execute(q.order_by(Hypothesis.created_at.desc()).limit(limit))).scalars().all()
    return [{"id": h.id, "title": h.title, "base": h.base, "changes": h.changes, "attempt": h.attempt,
             "status": h.status, "train_decision": h.train_decision,
             "confirmed": (h.verdict or {}).get("confirmed"), "created_at": h.created_at} for h in rows]
