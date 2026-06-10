# 🚀 Live Signal Generator - Инструкция по использованию

## 📋 Обзор

Live Signal Generator - модуль для генерации торговых сигналов в реальном времени на основе технических индикаторов. Сигналы отправляются в Telegram и сохраняются в PostgreSQL базу данных.

## ✅ Что уже реализовано

### 1. **PostgreSQL миграция**
- ✅ Таблица `backtester.trading_signals` создана
- ✅ 12 индексов для быстрого поиска
- ✅ Триггеры для автоматического обновления

### 2. **Live Signal Generator** (`live_signal_generator.py`)
- ✅ Подключение к Binance через CCXT WebSocket
- ✅ Проверка индикаторных стратегий (RSI, EMA, ADX, MACD)
- ✅ Расчет TP/SL уровней
- ✅ Генерация DCA сетки
- ✅ Сохранение сигналов в PostgreSQL
- ✅ Отправка Telegram уведомлений
- ✅ CLI интерфейс

### 3. **Telegram Bot интеграция**
- ✅ Функция `send_trading_signal_notification()` в `market-analytics/bot/notifications.py`
- ✅ Красивое форматирование сигналов
- ✅ Отображение индикаторов, TP/SL, DCA сетки

### 4. **Web API** (`web_app.py`)
- ✅ `POST /api/live-signals/start` - запуск генератора
- ✅ `POST /api/live-signals/stop` - остановка
- ✅ `GET /api/live-signals/status` - статус
- ✅ `GET /api/trading-signals/history` - история сигналов
- ✅ `GET /api/trading-signals/<signal_id>` - детали сигнала
- ✅ `GET /api/trading-signals/stats` - статистика

### 5. **Web UI** (`templates/live_signals.html`)
- ✅ Control Panel для управления
- ✅ Выбор стратегии из базы
- ✅ Настройка Telegram уведомлений
- ✅ Dry-run режим
- ✅ Статистика сигналов
- ✅ Таблица последних 20 сигналов
- ✅ Автообновление каждые 10 секунд

## 🚀 Быстрый старт

### Вариант 1: CLI (для тестирования)

```bash
# Dry-run режим (без сохранения в БД, только логи)
python live_signal_generator.py \
  --config ema_rsi_adx_crossover_15m_long.json \
  --telegram-user-id 297936848 \
  --dry-run

# Live режим (с сохранением в БД и Telegram уведомлениями)
python live_signal_generator.py \
  --config ema_rsi_adx_crossover_15m_long.json \
  --telegram-user-id 297936848 \
  --live
```

### Вариант 2: Docker CLI

```bash
# Запуск в Docker контейнере
docker-compose exec backtester-web python live_signal_generator.py \
  --config ema_rsi_adx_crossover_15m_long.json \
  --telegram-user-id 297936848 \
  --dry-run
```

### Вариант 3: Web UI (рекомендуется)

1. **Открой браузер:** http://localhost:8000/live-signals

2. **Выбери стратегию** из выпадающего списка

3. **Укажи Telegram User ID** (297936848)

4. **Включи Dry Run режим** для тестирования

5. **Нажми "Start Generator"**

6. **Наблюдай за сигналами** в таблице ниже

## 📊 Структура проекта

```
backtester/
├── live_signal_generator.py          # Основной модуль генератора
├── migrations/
│   └── 002_add_trading_signals.sql   # Миграция БД
├── market-analytics/
│   └── bot/
│       └── notifications.py          # Telegram уведомления
├── web_app.py                        # Flask app + API endpoints
└── templates/
    └── live_signals.html             # Web UI страница
```

## 🔧 Конфигурация

### Пример стратегии (`ema_rsi_adx_crossover_15m_long.json`):

```json
{
  "start_balance": 10000,
  "leverage": 1,
  "order_type": "long",
  "timeframe": "15m",

  "indicators": {
    "enabled": true,
    "strategy_type": "custom",
    "custom": {
      "selected_indicators": {
        "ema": true,
        "rsi": true,
        "adx": true
      },
      "ema": {
        "use_price_comparison": true,
        "period": 200
      },
      "rsi": {
        "period": 14,
        "use_crossover": true,
        "crossover_level_long": 38
      },
      "adx": {
        "period": 14,
        "max_value": 25
      }
    }
  },

  "take_profit": {
    "enabled": true,
    "target_percent": 3.0
  },

  "stop_loss": {
    "enabled": true,
    "stop_percent": 2.0
  },

  "data_source": {
    "type": "api",
    "exchange": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "15m"
  }
}
```

## 📱 Telegram уведомления

### Формат сигнала:

```
🟢 ТОРГОВЫЙ СИГНАЛ 🟢

📊 Рынок: BTC/USDT
⏰ Таймфрейм: 15m
📈 Направление: LONG
💰 Вход: $95,420.00

🎯 Take Profit: 3.00%
└─ Цена: $98,286.60

🛑 Stop Loss: 2.00%
└─ Цена: $93,511.60

📉 Индикаторы:
  🟢 RSI: 35.42
  📊 EMA50: $94,800.00
  ❄️ ADX: 18.50

⭐⭐⭐ Качество сигнала: 75/100

🕐 2026-02-01 12:34:56 UTC

Стратегия: custom_long
```

## 🗄️ База данных

### Структура таблицы `trading_signals`:

| Поле | Тип | Описание |
|------|-----|----------|
| `signal_id` | UUID | Уникальный ID сигнала |
| `timestamp` | TIMESTAMPTZ | Время генерации |
| `symbol` | VARCHAR(50) | Торговая пара (BTC/USDT) |
| `timeframe` | VARCHAR(10) | Таймфрейм (15m) |
| `side` | VARCHAR(10) | long/short |
| `entry_price` | NUMERIC | Цена входа |
| `take_profit_percent` | NUMERIC | TP в процентах |
| `take_profit_price` | NUMERIC | TP цена |
| `stop_loss_percent` | NUMERIC | SL в процентах |
| `stop_loss_price` | NUMERIC | SL цена |
| `indicators` | JSONB | Значения индикаторов |
| `quality_score` | NUMERIC | Оценка качества (0-100) |
| `status` | VARCHAR(20) | pending/notified/executed |

### SQL запросы:

```sql
-- Все сигналы за последние 24 часа
SELECT * FROM backtester.trading_signals
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;

-- Только LONG сигналы с качеством > 70
SELECT * FROM backtester.trading_signals
WHERE side = 'long' AND quality_score > 70
ORDER BY quality_score DESC;

-- Статистика по символам
SELECT symbol, COUNT(*), AVG(quality_score)
FROM backtester.trading_signals
GROUP BY symbol;
```

## 🎯 Оценка качества сигнала

Система автоматически рассчитывает качество сигнала (0-100) на основе:

- **+15 баллов** - Сильный RSI oversold/overbought (20-30 или 70-80)
- **+10 баллов** - Умеренный RSI (30-40 или 60-70)
- **+20 баллов** - Подтверждение тренда (EMA crossover)
- **+10 баллов** - Низкая волатильность (ADX < 25)
- **+5 баллов** - Сильный тренд (ADX > 25)
- **+5 баллов** - MACD подтверждение

**Базовый score:** 50

**Максимум:** 100

## ⚙️ API Endpoints

### Управление генератором

**POST** `/api/live-signals/start`
```json
{
  "config_name": "ema_rsi_adx_crossover_15m_long",
  "telegram_user_id": "297936848",
  "dry_run": true
}
```

**POST** `/api/live-signals/stop`
```json
{
  "config_name": "ema_rsi_adx_crossover_15m_long"
}
```

**GET** `/api/live-signals/status`

### Получение сигналов

**GET** `/api/trading-signals/history?limit=20&symbol=BTC/USDT&side=long`

**GET** `/api/trading-signals/stats`

**GET** `/api/trading-signals/<signal_id>`

## 🔒 Безопасность

### Dry Run режим (по умолчанию)
- ✅ Сигналы НЕ сохраняются в БД
- ✅ Telegram уведомления НЕ отправляются
- ✅ Только логи в консоль
- ✅ Безопасное тестирование

### Live режим
- ⚠️ Сигналы сохраняются в PostgreSQL
- ⚠️ Telegram уведомления отправляются
- ⚠️ Используй только после тестирования!

### Rate Limiting
- **Cooldown:** 5 минут между сигналами
- **Duplicate prevention:** Нет повторных сигналов на одной свече
- **Max entries per bar:** Настраивается в конфиге

## 🐛 Отладка

### Логи

```bash
# Смотреть логи в реальном времени (CLI)
python live_signal_generator.py --config ... --dry-run

# Логи Docker контейнера
docker-compose logs -f backtester-web

# Telegram бот логи
docker-compose logs -f backtester_telegram_bot
```

### Проверка БД

```bash
# Подключение к PostgreSQL
docker-compose exec postgres psql -U backtester -d backtester

# Проверить таблицу
\d backtester.trading_signals

# Последние 10 сигналов
SELECT signal_id, timestamp, symbol, side, entry_price, quality_score
FROM backtester.trading_signals
ORDER BY timestamp DESC
LIMIT 10;
```

## 🚧 TODO (будущие улучшения)

- [ ] Background thread для live генератора в web_app.py
- [ ] WebSocket push уведомления в UI
- [ ] Multi-symbol мониторинг (BTC, ETH, SOL одновременно)
- [ ] Auto-adjust TP/SL на основе волатильности
- [ ] Integration с CryptoRG webhook
- [ ] Backtesting прошлых сигналов
- [ ] Position tracking из реальной биржи

## 💡 Рекомендации

1. **Начни с Dry Run** - Протестируй 1-2 недели без сохранения
2. **Оптимизируй стратегию** - Используй optimizer.py для подбора параметров
3. **Мониторь качество** - Отслеживай quality_score, цель > 70
4. **Проверяй на истории** - Backtest перед live режимом
5. **Используй Telegram** - Удобнее чем смотреть БД
6. **Paper trading сначала** - Тестируй без реальных денег

## 📞 Поддержка

При проблемах проверь:
- ✅ Docker контейнеры запущены: `docker-compose ps`
- ✅ Миграция применена: `\d backtester.trading_signals`
- ✅ Telegram бот токен настроен: `.env` → `TELEGRAM_BOT_TOKEN`
- ✅ PostgreSQL доступен: `docker-compose exec postgres psql -U backtester`

## 🎉 Готово!

Теперь у тебя есть полноценный live signal generator с:
- ✅ Real-time мониторингом рынка
- ✅ Telegram уведомлениями
- ✅ Веб-интерфейсом
- ✅ Сохранением в БД
- ✅ Статистикой и аналитикой

**Следующий шаг:** Интеграция с CryptoRG webhook для автоматической торговли! 🚀
