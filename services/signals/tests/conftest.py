import os

# Settings требует DATABASE_URL; движок создаётся лениво и в тестах к базе не подключается
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
