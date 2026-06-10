# ⚡ Live Signals - Быстрый старт

## 🎯 Что это?

Live Signal Generator генерирует торговые сигналы в реальном времени на основе индикаторов (RSI, EMA, ADX, MACD) и отправляет их в Telegram.

## 🚀 Запуск за 3 шага

### 1️⃣ Открой веб-интерфейс

```
http://localhost:8000/live-signals
```

### 2️⃣ Настрой параметры

- **Strategy:** Выбери `ema_rsi_adx_crossover_15m_long` (или любую другую)
- **Telegram User ID:** `297936848` (твой ID)
- **Dry Run Mode:** ✅ Включи (для тестирования без сохранения в БД)

### 3️⃣ Запусти генератор

Нажми **"Start Generator"** → жди сигналов!

## 📱 Формат Telegram сигнала

```
🟢 ТОРГОВЫЙ СИГНАЛ 🟢

📊 Рынок: BTC/USDT
⏰ Таймфрейм: 15m
📈 Направление: LONG
💰 Вход: $95,420.00

🎯 Take Profit: 3.00% ($98,286.60)
🛑 Stop Loss: 2.00% ($93,511.60)

📉 Индикаторы:
  🟢 RSI: 35.42
  📊 EMA50: $94,800
  ❄️ ADX: 18.5

⭐⭐⭐ Качество: 75/100
```

## 🔧 CLI тестирование (опционально)

```bash
# Dry-run режим (только логи, без БД)
python live_signal_generator.py \
  --config ema_rsi_adx_crossover_15m_long.json \
  --telegram-user-id 297936848 \
  --dry-run

# Live режим (сохранение в БД + Telegram)
python live_signal_generator.py \
  --config ema_rsi_adx_crossover_15m_long.json \
  --telegram-user-id 297936848 \
  --live
```

## 📊 Просмотр истории сигналов

### Web UI:
```
http://localhost:8000/live-signals
```
Таблица внизу страницы автоматически обновляется каждые 10 секунд.

### SQL:
```bash
docker-compose exec postgres psql -U backtester -d backtester

SELECT signal_id, timestamp, symbol, side, entry_price, quality_score
FROM backtester.trading_signals
ORDER BY timestamp DESC
LIMIT 10;
```

### API:
```bash
curl http://localhost:8000/api/trading-signals/history?limit=10 | python3 -m json.tool
```

## ⚠️ Важно!

### Dry Run vs Live режим

| Режим | Сохранение в БД | Telegram | Безопасность |
|-------|----------------|----------|--------------|
| **Dry Run** ✅ | ❌ Нет | ❌ Нет | ✅ Безопасно |
| **Live** ⚠️ | ✅ Да | ✅ Да | ⚠️ Осторожно |

**Рекомендация:** Тестируй 1-2 недели в Dry Run режиме перед Live!

## 🎛️ Настройка стратегии

Создай свою стратегию в **Конфигурация** → Сохрани → Используй в Live Signals.

**Ключевые параметры:**
- `indicators.enabled: true` - Включить индикаторы
- `indicators.strategy_type` - Тип стратегии (custom, trend_momentum, volatility_bounce)
- `take_profit.target_percent` - TP в процентах
- `stop_loss.stop_percent` - SL в процентах

## 📈 Следующие шаги

1. ✅ Протестируй в Dry Run режиме
2. ✅ Оптимизируй стратегию через **Optimizer**
3. ✅ Запусти в Live режиме
4. ✅ Мониторь сигналы в Telegram
5. ✅ (Будущее) Интеграция с CryptoRG webhook для автоматической торговли

## 🆘 Проблемы?

**Сигналы не приходят:**
- Проверь что стратегия содержит `indicators.enabled: true`
- Убедись что рынок активен (Binance доступен)
- Посмотри логи: `docker-compose logs -f backtester-web`

**Telegram не отправляется:**
- Проверь `.env` → `TELEGRAM_BOT_TOKEN`
- Убедись что включен Live режим (не Dry Run)
- Проверь Telegram бот: `docker-compose logs -f backtester_telegram_bot`

**БД пустая:**
- Убедись что **Dry Run отключен** (только Live режим сохраняет в БД)
- Проверь что миграция применена: `\d backtester.trading_signals`

## 🎉 Готово!

Теперь система:
- ✅ Мониторит BTC/USDT в реальном времени
- ✅ Генерирует сигналы на основе индикаторов
- ✅ Отправляет уведомления в Telegram
- ✅ Сохраняет историю в PostgreSQL
- ✅ Показывает статистику в Web UI

**Полная документация:** `LIVE_SIGNALS_README.md`
