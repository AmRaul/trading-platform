from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class Hypothesis(Base):
    """Журнал гипотез (MCP): что проверяли, каким критерием, сколько раз и чем кончилось.

    Защита от подгонки: гипотеза и критерий успеха записываются ДО прогона и не меняются;
    после прогона виден только обучающий период; отложенный открывается один раз — после
    решения по обучающему (reveal). idea_key — стратегия + какие параметры меняли:
    по нему считается номер попытки «той же идеи».
    """
    __tablename__ = "hypotheses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    rationale = Column(Text, nullable=True)          # почему должно сработать
    success_criterion = Column(Text, nullable=False)  # что считаем успехом — до прогона
    base = Column(String, nullable=False)             # alt_short | mrc_dca
    changes = Column(JSON, nullable=False)            # {параметр: значение}
    idea_key = Column(String, nullable=False, index=True)
    attempt = Column(Integer, nullable=False, default=1)
    # running → tested (виден обучающий) → revealed (виден и отложенный); error
    status = Column(String, nullable=False, default="running")
    task_id = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)              # полный итог бэктестера (с отложенным — не отдаётся до reveal)
    train_decision = Column(String, nullable=True)    # passes | fails — решение по обучающему периоду
    decision_note = Column(Text, nullable=True)
    verdict = Column(JSON, nullable=True)             # итог после отложенного периода
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    revealed_at = Column(DateTime(timezone=True), nullable=True)
