from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True)
    is_active = Column(Boolean, default=True)  # False — заблокирован админом
    # Регистрация ждёт одобрения админа (кроме ADMIN_USERNAME); до него вход закрыт
    approved = Column(Boolean, default=False, nullable=False, server_default="false")
    # Личный Telegram: уведомления о сделках и алерты по своим ботам
    telegram_chat_id = Column(String, nullable=True)
    telegram_notify = Column(String, default="all", nullable=False, server_default="all")  # all | real | off
    telegram_link_code = Column(String, nullable=True, unique=True, index=True)
    telegram_link_expires = Column(DateTime(timezone=True), nullable=True)
    plan = Column(String, default="free")  # free / pro
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
