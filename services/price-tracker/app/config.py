from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://redis:6379/0"
    BYBIT_TESTNET: bool = False
    # Comma-separated list of symbols to track on startup, e.g. "BTCUSDT,SOLUSDT"
    # In production these are populated dynamically via the subscription API.
    DEFAULT_SYMBOLS: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
