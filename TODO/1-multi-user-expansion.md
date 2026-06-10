# TODO: Расширение на multi-user

**Статус:** План утверждён, не начат. 2026-06-05.  
**Приоритет:** Высокий — нужен перед открытием для других пользователей.

---

## Фазы реализации

### Фаза 1 — Хранение API ключей (критический)

Новая таблица `user_credentials`:
```python
class UserCredential(Base):
    __tablename__ = "user_credentials"
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    exchange    = Column(String, default="cryptorg")
    webhook_url = Column(String, nullable=False)   # зашифрован
    api_key     = Column(String, nullable=True)    # зашифрован
    api_secret  = Column(String, nullable=True)    # зашифрован
    created_at  = Column(DateTime, server_default=func.now())
    updated_at  = Column(DateTime, onupdate=func.now())
```

Шифрование: `cryptography.fernet`, ключ в `.env` как `ENCRYPTION_KEY`.  
Файлы: `models/user_credential.py`, `core/encryption.py`, alembic миграция.

CryptorgClient — фабрика вместо синглтона:
```python
def get_cryptorg_client(credential: UserCredential) -> CryptorgClient:
    return CryptorgClient(webhook_url=decrypt(credential.webhook_url))
```

---

### Фаза 2 — user_id в моделях (критический)

Добавить `user_id` FK в: `Bot`, `Position`, `Order`, `Trade`.  
`SignalLog`, `TrendSignalLog`, `ScreenerSnapshot` — остаются глобальными.  
Одна alembic миграция на все таблицы.

---

### Фаза 3 — Изоляция данных в роутах (критический)

Паттерн: `select(Bot).where(Bot.user_id == current_user.id)` — во всех роутах.  
Файлы: `routes/bots.py`, `positions.py`, `trades.py`, `trading.py`.

Redis keys — namespace пользователя:
```
# Было:  position:{bot_id}
# Стало: position:{user_id}:{bot_id}
```
Файл: `core/redis.py`

---

### Фаза 4 — User model расширение

Добавить в `User`: `email`, `is_active`, `is_verified`, `plan` (free/pro).  
API endpoint `GET/PUT /api/profile/credentials` для ввода ключей через UI.

---

### Фаза 5 — Price Tracker отдельный сервис

Отдельный процесс `price-tracker/`:
- Получает `symbol + exchange` через `redis.subscribe("track_requests")` (формат: `SOLUSDT:bybit`)
- Подписывается на WS нужной биржи, пишет `price:{symbol}` в Redis
- Публикует `redis.publish("prices", f"{symbol}:{price}")`
- Бэкенд читает из Redis SUB — не зависит от конкретной биржи

**Поддерживаемые биржи:**
- Bybit — `pybit` WebSocket, channel_type="linear"
- Binance — `python-binance` или `websockets`, stream `{symbol}@ticker`
- MEXC — `websockets`, stream `spot@public.miniTickers.v3.api`

Архитектура трекера:
```python
ADAPTERS = {
    "bybit":   BybitWSAdapter(),
    "binance": BinanceWSAdapter(),
    "mexc":    MEXCWSAdapter(),
}

async def track(symbol: str, exchange: str):
    adapter = ADAPTERS[exchange]
    adapter.subscribe(symbol, on_price)
```

Добавить в `docker-compose.yml` как отдельный сервис с `restart: always`.

---

### Фаза 6 — Screener/Trend (низкий приоритет)

Оставить глобальными — рыночные данные одинаковы для всех пользователей.  
Вынос в backtester — отдельная задача позже.

---

## Что НЕ трогаем

- Screener/Trend — глобальные, это правильно
- Backtester — отдельный проект
- Celery/sharding воркеры — нужны при 500+ ботах, не сейчас
