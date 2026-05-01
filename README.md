# Trading Dashboard + Trend Pyramiding Bot

Локальная торговая система с мониторингом рынка, ручным запуском торговых ботов и управлением позициями с поддержкой trend pyramiding (добавление в прибыль) и dynamic SL от средней цены позиции.

## 🎯 Основная концепция

**Trend Pyramiding** — стратегия управления позицией, где риск не фиксируется на входе, а управляется через среднюю цену позиции и динамический стоп-лосс.

### Как это работает:

1. **Ручной вход** (25% депозита)
   - Входим с фиксированным SL = -5%
   - Ждём развития тренда

2. **Автоматические доборы** (pyramiding)
   - При движении цены на +4% от последнего ордера → добавляем позицию
   - Размер нового ордера = предыдущий × 1.5
   - Максимум 4 ордера (1 вход + 3 добора)
   - **Важно:** доборы только в прибыль, никакого усреднения убытка

3. **Динамический Stop Loss** (после 2-го ордера)
   - Пересчитываем среднюю цену всей позиции
   - Новый SL = avg_price + 2% (для long)
   - SL только двигается вверх (в сторону прибыли)

4. **Trailing Stop** (опционально)
   - Активируется после 2-го ордера
   - Тянется за ценой на расстоянии 1.5%
   - Выбираем лучший: `final_SL = max(dynamic_SL, trailing_SL)`

5. **Выход**
   - Цена касается SL → закрываем всю позицию
   - Или ручное закрытие из UI

---

## 🏗️ Архитектура

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Next.js UI    │◄────►│  FastAPI Backend │─────▶│   Cryptorg API  │
│  (Dashboard)    │      │  (Strategy Core) │      │    (Trading)    │
└─────────────────┘      └──────────────────┘      └─────────────────┘
         │                        │
         │                        ▼
         │               ┌─────────────────┐
         │               │   Bybit API     │
         │               │ (Price Data)    │
         │               └─────────────────┘
         ▼                        ▼
┌─────────────────┐      ┌──────────────────┐
│   WebSocket     │      │   PostgreSQL     │
│  (Live updates) │      │   + Redis        │
└─────────────────┘      └──────────────────┘
```

**Frontend:** Next.js 14 + Tailwind CSS + TanStack Query
**Backend:** FastAPI + SQLAlchemy + Redis
**Database:** PostgreSQL 16 + Redis 7
**Price Data:** Bybit Futures API (WebSocket + REST)
**Trading:** Cryptorg Webhook API

---

## 🚀 Быстрый старт

### 1. Клонирование и настройка

```bash
cd "dashboard trend strategy"
```

### 2. Настройка окружения

Создайте файл `.env` на основе `.env.example`:

```bash
cp .env.example .env
```

Заполните API credentials:

```env
# Bybit (для получения цен)
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_secret
BYBIT_TESTNET=false

# Cryptorg (для реальной торговли)
CRYPTORG_WEBHOOK_URL=https://api.cryptorg.io/webhook
CRYPTORG_API_KEY=your_cryptorg_api_key
CRYPTORG_SECRET=your_cryptorg_secret

# Security
SECRET_KEY=your-super-secret-key-change-this
```

**Важно:**
- **Bybit** используется ТОЛЬКО для получения live цен (бесплатно, без торговли)
- **Cryptorg** используется для реального исполнения сделок

Подробнее: [CRYPTORG_INTEGRATION.md](CRYPTORG_INTEGRATION.md)

### 3. Запуск через Docker

```bash
docker-compose up --build
```

**Сервисы будут доступны:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### 4. Первый запуск

1. Откройте http://localhost:3000
2. Зарегистрируйтесь (создайте аккаунт)
3. Войдите в систему
4. Перейдите в раздел "Bots" → "Create Bot"
5. Настройте параметры стратегии
6. Нажмите "Enter" для входа в позицию

---

## 📊 Конфигурация стратегии

### Основные параметры:

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `order_count` | Максимальное количество ордеров | 4 |
| `entry_size` | Размер первого ордера (% от депозита) | 25% |
| `step_percent` | Шаг для добора (% от последнего ордера) | 4% |
| `leverage` | Плечо | 10x |
| `pyramiding_multiplier` | Множитель размера для каждого добора | 1.5 |
| `sl_initial` | Начальный SL для первого ордера | 5% |
| `sl_dynamic_offset` | Отступ SL от средней цены (после 2-го ордера) | 2% |
| `use_trailing` | Использовать trailing stop | true |
| `trailing_percent` | Расстояние trailing stop от цены | 1.5% |

### Пример конфигурации:

```json
{
  "order_count": 4,
  "entry_size": 0.25,
  "step_percent": 4.0,
  "leverage": 10,
  "pyramiding_multiplier": 1.5,
  "sl_initial": 5.0,
  "sl_dynamic_offset": 2.0,
  "use_trailing": true,
  "trailing_percent": 1.5
}
```

---

## 💡 Пример работы стратегии

**Депозит:** $1000
**Символ:** BTC/USDT
**Направление:** LONG
**Стартовая цена:** $50,000

### Сценарий:

1. **Ордер #1:** $250 @ $50,000
   - SL = $47,500 (-5%)

2. **Цена → $52,000 (+4%)**
   - **Ордер #2:** $375 @ $52,000
   - Средняя цена = $51,200
   - **Новый SL = $52,224** (+2% от avg) ✅ В прибыли!

3. **Цена → $54,080 (+4% от $52k)**
   - **Ордер #3:** $562.5 @ $54,080
   - Средняя цена = $52,640
   - **Новый SL = $53,693**

4. **Цена разворачивается и касается SL**
   - Закрываем всю позицию → выход с прибылью

---

## 🎮 UI модули

### Dashboard
- Активные боты
- Общий PnL
- Открытые позиции

### Bots
- Создание/удаление ботов
- Ручной вход/выход
- Настройка параметров стратегии

### Positions
- Live мониторинг открытых позиций
- Текущая цена, avg price, SL
- Unrealized PnL

### History
- История закрытых сделок
- Win rate
- PnL по каждой сделке

---

## 🔧 Разработка

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or venv\Scripts\activate  # Windows

pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
```

### Database migrations

```bash
cd backend
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

---

## 📡 API Endpoints

### Authentication
- `POST /api/auth/register` - Регистрация
- `POST /api/auth/login` - Вход

### Bots
- `GET /api/bots` - Список ботов
- `POST /api/bots` - Создать бота
- `PATCH /api/bots/{id}` - Обновить бота
- `DELETE /api/bots/{id}` - Удалить бота

### Trading
- `POST /api/trading/entry` - Ручной вход
- `POST /api/trading/close` - Ручной выход

### Positions
- `GET /api/positions` - Список позиций
- `GET /api/positions/bot/{bot_id}` - Позиции бота

### Trades
- `GET /api/trades` - История сделок
- `GET /api/trades/bot/{bot_id}` - Сделки бота

### WebSocket
- `WS /api/ws` - Live обновления (цены, PnL, SL)

---

## 🛡️ Безопасность

1. **API ключи Bybit** хранятся в `.env` (не коммитить!)
2. **JWT токены** для аутентификации
3. **Ограничения:**
   - Max exposure per bot
   - Max number of bots
   - No averaging down (строго запрещено)

---

## ⚠️ Важные замечания

### Что система ДЕЛАЕТ:
✅ Управление позициями с умным риск-менеджментом
✅ Trend following с pyramiding
✅ Dynamic SL от средней цены
✅ Live мониторинг и контроль

### Что система НЕ ДЕЛАЕТ:
❌ Автоматические сигналы входа
❌ ML/AI прогнозы
❌ Усреднение убытков (мартингейл)
❌ HFT или арбитраж

---

## 📝 State Machine

```
IDLE → ENTRY → PYRAMIDING → EXIT
  ↑                           │
  └───────────────────────────┘
```

**IDLE:** Бот создан, ждёт ручного входа
**ENTRY:** Первый ордер размещён
**PYRAMIDING:** Активны доборы при движении цены
**EXIT:** Позиция закрыта (SL hit / manual close)

---

## 🐛 Troubleshooting

### Backend не запускается
```bash
# Проверьте PostgreSQL и Redis
docker-compose ps

# Проверьте логи
docker-compose logs backend
```

### Frontend не подключается к API
```bash
# Проверьте NEXT_PUBLIC_API_URL в .env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

### Ошибки Bybit API
- Проверьте API ключи
- Убедитесь, что IP whitelisted (если включено)
- Проверьте права API ключа (нужны: Orders, Positions)

---

## 📚 Технологии

**Backend:**
- FastAPI 0.115+
- SQLAlchemy 2.0 (async)
- PostgreSQL 16
- Redis 7
- pybit (Bybit SDK для price data)
- aiohttp (Cryptorg webhook client)

**Frontend:**
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- TanStack Query
- Zustand (state)
- Recharts (графики)

**Integration:**
- **Bybit API** — live цены через WebSocket
- **Cryptorg Webhook API** — исполнение сделок

**DevOps:**
- Docker + Docker Compose
- Nginx (опционально для prod)

---

## 🎯 Roadmap

- [x] MVP: Ручной вход + pyramiding + dynamic SL
- [x] Bybit integration (price data)
- [x] Cryptorg webhook integration (trading)
- [ ] Адаптация под реальную Cryptorg документацию
- [ ] Stop Loss ордера на бирже
- [ ] Backtesting на исторических данных
- [ ] Notifications (Telegram)
- [ ] Advanced analytics (Sharpe ratio, drawdown)
- [ ] Multi-exchange support
- [ ] Paper trading mode

---

## 📄 Документация

- **[README.md](README.md)** — главная документация
- **[CRYPTORG_INTEGRATION.md](CRYPTORG_INTEGRATION.md)** — интеграция с Cryptorg
- **[CRYPTORG_CUSTOMIZATION_GUIDE.md](CRYPTORG_CUSTOMIZATION_GUIDE.md)** — адаптация под реальный API
- **[INTEGRATION_SUMMARY.md](INTEGRATION_SUMMARY.md)** — итоговая сводка

---

## ⚠️ Важно перед запуском

1. **Получите документацию Cryptorg** с https://docs.cryptorg.io/cryptorg-bot_futures/webhooks
2. **Адаптируйте** `backend/app/services/cryptorg.py` под реальный формат API
3. **Протестируйте** на минимальных объёмах ($1-10)
4. **Настройте** `.env` с реальными credentials

---

## 📄 Лицензия

MIT License

---

## 👨‍💻 Контакты

По вопросам и предложениям создавайте Issues в репозитории.

---

**⚡️ Happy Trading! ⚡️**
