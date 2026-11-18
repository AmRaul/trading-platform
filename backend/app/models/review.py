from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Review(Base):
    """Журнал разборов (пишет MCP): ежемесячные разборы форвард-теста,
    проверки «живы ли боты», второе мнение по позиции.

    bot_id/position_id без внешних ключей: запись журнала переживает
    удаление бота и не мешает его удалить.
    """
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)  # monthly_review | health_check | second_opinion | note
    bot_id = Column(Integer, nullable=True, index=True)
    position_id = Column(Integer, nullable=True, index=True)
    symbol = Column(String, nullable=True)
    summary = Column(Text, nullable=False)
    # second_opinion: {action, first_hit, confidence, key_risk, ...} — проверяемый вердикт
    verdict = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
