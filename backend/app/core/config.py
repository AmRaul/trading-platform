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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    ENCRYPTION_KEY: str = ""

    # CORS
    BACKEND_CORS_ORIGINS: list = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
