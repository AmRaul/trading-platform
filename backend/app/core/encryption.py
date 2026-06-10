from cryptography.fernet import Fernet
from app.core.config import settings


def _cipher() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _cipher().decrypt(value.encode()).decode()
