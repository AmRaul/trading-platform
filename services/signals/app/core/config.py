from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    BYBIT_TESTNET: bool = False
    SECRET_KEY: str = "signals-internal-secret"

    model_config = {"env_file": ".env"}


settings = Settings()
