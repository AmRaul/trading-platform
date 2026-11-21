from sqlalchemy import Column, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class StateSnapshot(Base):
    """Снимок состояния ботов для what_changed (MCP): стоп, плавающий PnL, состояние.

    Входы, доборы и закрытия и так лежат в positions/orders/trades со временем, а сдвиг
    стопа, изменение плавающего PnL и удалённого бота видно только сравнением со
    снимком. Каждый вызов /api/analytics/changes сравнивает с прошлым снимком и пишет новый.
    """
    __tablename__ = "state_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    taken_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    # {bot_id: {name, symbol, side, exchange, state, total_pnl, position_id, sl, unrealized_pnl, order_count}}
    data = Column(JSON, nullable=False)
