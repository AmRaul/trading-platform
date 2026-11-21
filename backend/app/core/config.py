from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # Bybit (for public price data only, no API keys needed)
    BYBIT_TESTNET: bool = False

    # Cryptorg (for actual trading)
    CRYPTORG_BASE_URL: str = "https://api2.cryptorg.net"
    CRYPTORG_WEBHOOK_URL: str = ""
    CRYPTORG_API_KEY: str = ""
    CRYPTORG_SECRET: str = ""

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    # Короткий access-токен (в памяти браузера, заголовок Authorization) +
    # долгий refresh-токен в httpOnly-cookie (/api/auth/refresh): украденный из JS
    # access-токен живёт полчаса, а refresh скрипту страницы недоступен.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ENCRYPTION_KEY: str = ""

    # Admin access — single-owner dashboard, no role system. /api/admin/*
    # checks current_user.username against this value.
    ADMIN_USERNAME: str = ""

    # Price Tracker service URL
    PRICE_TRACKER_URL: str = "http://price-tracker:8010"

    # Уведомления о сделках в Telegram (services/telegram_notifier.py); тот же бот и чат, что у алертера.
    # TELEGRAM_NOTIFY: all — все боты, real — без бумажных, off — выключено
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    TELEGRAM_NOTIFY: str = "all"

    # CORS
    BACKEND_CORS_ORIGINS: list = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
