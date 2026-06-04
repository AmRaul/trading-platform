# TODO: Поддержка нескольких бирж (Bybit, MEXC, др.)

**Статус:** Идея, не реализована. 2026-06-04.  
**Приоритет:** Низкий — актуально когда появится потребность торговать напрямую без Cryptorg.

---

## Что нужно сделать

### 1. Модель Bot — добавить поле exchange
```python
exchange = Column(String, nullable=False, default="bybit")  # bybit / mexc / binance
```
Миграция Alembic. UI при создании бота — дропдаун выбора биржи.

### 2. Рефакторинг PriceStreamManager
Сейчас жёстко завязан на BybitClient. Нужна карта клиентов:
```python
ws_clients: Dict[str, WebSocketClient] = {
    "bybit": BybitWebSocket(),
    "mexc": MEXCWebSocket(),
}
```
Каждый бот регистрируется в нужном потоке по `bot.exchange`.

### 3. Новые адаптеры
- `adapters/bybit_executor.py` — прямой Bybit API (pybit), SL/TP в ценах (не %)
- `adapters/mexc_executor.py` — MEXC API
- `adapters/mexc_market_data.py` — MEXC WebSocket + OHLCV

### 4. StrategyEngine — выбор адаптера по бирже
```python
executor = {
    "bybit": BybitExecutorAdapter(),
    "mexc": MEXCExecutorAdapter(),
    "cryptorg": CryptorgExecutorAdapter(),
}[bot.exchange]
```

---

## Главная сложность

**SL/TP формат:** Cryptorg принимает проценты, Bybit/MEXC напрямую — цены.  
`PositionCalculator.calculate_stop_loss()` возвращает цену — использовать её для прямых бирж.  
`calculate_sl_percent()` — только для Cryptorg.

**WebSocket изоляция:** боты на разных биржах слушают разные потоки, цены не смешиваются.

---

## Что уже готово

Архитектура портов и адаптеров полностью готова к этому:
- `ports/exchange_executor.py` — интерфейс исполнения
- `ports/market_data.py` — интерфейс данных
- `adapters/bybit_market_data.py` — уже есть, расширить до WebSocket
- Вся торговая логика в доменном слое — не зависит от биржи
