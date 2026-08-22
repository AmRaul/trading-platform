# Trading Platform — Trend Pyramiding + Multi-Service Backend

Торговая платформа для управления позициями со стратегией **trend pyramiding** (доборы только в прибыль, без усреднения убытка) и **dynamic Stop Loss** от средней цены позиции. Помимо основного торгового движка включает отдельные сервисы для скринера рынка/трендовых сигналов и бэктестинга стратегий на исторических данных.

## Основная концепция: Trend Pyramiding

Риск не фиксируется на входе, а управляется через среднюю цену позиции и динамический стоп-лосс.

1. **Вход** — ручной или по лимитной цене (`WAITING` → бот ждёт указанную цену, затем открывает позицию)
2. **Пирамидинг** — при движении цены на `step_percent` от последнего ордера в прибыльную сторону добавляется новый ордер размером `предыдущий × pyramiding_multiplier`, максимум `order_count` ордеров. Доборы **только в прибыль** — усреднение убытка (мартингейл) исключено намеренно.
3. **Dynamic Stop Loss** (после 2-го ордера) — пересчитывается средняя цена позиции, новый SL = `avg_price ± sl_dynamic_offset`, двигается только в сторону прибыли.
4. **Trailing Stop** (опционально) — тянется за ценой, итоговый SL = `max(dynamic_SL, trailing_SL)`.
5. **Выход** — по срабатыванию SL или ручным закрытием из UI.

Исполнение сделок идёт через **Cryptorg** (webhook API); **Bybit** используется только как бесплатный источник live-цен (публичные WebSocket-тикеры, без API-ключей и торговых прав).

## Архитектура

Это монорепозиторий из независимо разворачиваемых сервисов — у каждого своя БД (кроме price-tracker, который БД не использует) и свой CI/CD pipeline.

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────┐
│  Next.js UI  │────▶│  backend/         │────▶│  Cryptorg    │
│  (frontend)  │     │  Execution Service│     │  (исполнение)│
└──────┬───────┘     │  (FastAPI)        │     └──────────────┘
       │             └────┬──────────┬───┘
       │                  │          │
       │           Redis pub/sub  Postgres
       │                  │        (trading_db)
       │                  ▼
       │          ┌───────────────────┐      ┌─────────────┐
       │          │ price-tracker     │─────▶│  Bybit WS   │
       │          │ (Bybit → Redis)   │      │ (цены)      │
       │          └───────────────────┘      └─────────────┘
       │
       ├────────▶ services/signals (скринер, тренд-сигналы) — своя БД (signals_db)
       │
       └────────▶ services/backtester (бэктест стратегий) — своя БД (backtester)
```

Frontend обращается к трём независимым backend-URL напрямую из браузера (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SIGNALS_URL`, `NEXT_PUBLIC_BACKTESTER_URL`) — сервисы друг про друга не знают, кроме связки backend ↔ price-tracker через Redis.

### backend/ — Execution Service

Основной торговый движок (FastAPI + SQLAlchemy async). Владеет пользователями, ботами, позициями, ордерами, сделками, Cryptorg-аккаунтами.

- **Боты** — `Bot` с состояниями `IDLE → WAITING → ENTRY → PYRAMIDING → EXIT`, конфигурация стратегии хранится в JSON-колонке `config` (per-bot: `order_count`, `step_percent`, `pyramiding_multiplier`, `sl_initial`, `sl_dynamic_offset`, `trailing_percent`, `bot_type` и др.)
- **Multi-account** — один пользователь может завести несколько `CryptorgAccount` (разные webhook URL/ключи) и привязать каждого бота к конкретному аккаунту
- **DCA vs Pyramiding боты** — `bot_type: "dca"` отдаёт лимитную сетку ордеров нативно Cryptorg; `bot_type: "pyramiding"` — доборы считает и инициирует сам backend
- **Realtime** — `price_stream_manager` слушает Redis pub/sub от price-tracker и прогоняет каждый тик через `StrategyEngine.on_price_update()`; при рестарте `restore_active_strategies()` заново поднимает активные стратегии из БД
- Слоистая архитектура: `api/routes` (HTTP) → `services/strategy.py` (оркестратор) → `application/trading/*` (use cases: open/close/add pyramiding order) → `domain/trading/*` (чистая логика расчётов)

Основные группы роутов (`backend/app/api/routes/`): `auth`, `bots`, `trading` (вход/выход/лимитные ордера), `positions`, `trades`, `accounts` (multi-account CRUD), `websocket` (`/api/ws` — live цены/PnL/SL). Роуты `profile`, `signals`, `trend_signals` — устаревшие/неиспользуемые, функциональность перенесена в `accounts` и `services/signals` соответственно.

### services/price-tracker/

Отдельный лёгкий FastAPI-сервис: держит WebSocket-подключения к Bybit (`pybit`, публичные ticker-стримы) и публикует цены в Redis pub/sub. Backend подписывается на нужные символы через внутренний HTTP API (`POST/DELETE /subscribe`) при регистрации/снятии стратегии бота. Работает только внутри docker-сети, наружу порт не пробрасывается.

### services/signals/

Независимый сервис (своя БД `signals_db`), не связан с backend напрямую — фронтенд обращается к нему отдельно. Два фоновых сканера:
- **Screener** — раз в 15 минут сканирует весь рынок, классифицирует по Vol 1h + Range% (PUMPING/DUMPING/COOLING)
- **Trend** — отслеживает тренд (EMA21 4h/1h) по настраиваемому watch-list символов (по умолчанию альты с объёмом: SOL, AVAX, LINK, ETH, BNB, DOT, AAVE)
- **Signal strategies** — настраиваемые правила детекции (встроенные: MOMENTUM, REVERSAL, BREAKOUT)

### services/backtester/

Отдельное Flask-приложение с CLI и веб-UI для бэктестинга стратегий (Long/Short DCA + martingale, EMA/RSI/ADX-фильтры, MRC — Mean Reversion Channel) на исторической OHLCV-истории через CCXT. Своя БД (`backtester`), свои миграции. Встроен также как страница внутри основного Next.js-фронтенда (`frontend/app/backtester`). Подробнее — `services/backtester/README.md`.

## Frontend

Next.js 14 (App Router) + TypeScript + Tailwind + TanStack Query.

| Страница | Назначение |
|---|---|
| `dashboard` | Обзор: активные боты, суммарный PnL, открытые позиции |
| `bots` | CRUD ботов, ручной вход/выход, лимитный вход, конфиг стратегии, привязка аккаунта |
| `positions` | Live-мониторинг открытых позиций (цена, avg price, SL, unrealized PnL) |
| `history` | История закрытых сделок, win rate |
| `accounts` | CRUD Cryptorg-аккаунтов (multi-account) |
| `screener` | Кандидаты со скринера (`services/signals`) |
| `signals` / `trend-signals` | Залогированные сигналы скринера / тренд-детектора |
| `signal-strategies` | CRUD правил детекции сигналов |
| `trend-symbols` | Watch-list символов для тренд-сканера |
| `backtester` | Запуск и мониторинг бэктестов |
| `login` | Вход/регистрация |

## Быстрый старт (docker compose)

```bash
cp .env.example .env    # заполнить секреты
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API + Swagger: http://localhost:8000/docs
- Signals API: http://localhost:8020
- Grafana (логи, если поднят стек мониторинга): см. `docker-compose.yml`

Первый запуск: зарегистрироваться → создать Cryptorg-аккаунт (Accounts) → создать бота (Bots) → задать конфиг стратегии → войти в позицию.

## Конфигурация стратегии (пример)

| Параметр | Описание | По умолчанию |
|---|---|---|
| `order_count` | Максимум ордеров (вход + доборы) | 4 |
| `entry_size` | Размер первого ордера, % депозита | 25% |
| `step_percent` | Шаг цены для добора | 4% |
| `pyramiding_multiplier` | Множитель размера каждого добора | 1.5 |
| `sl_initial` | Начальный SL первого ордера | 5% |
| `sl_dynamic_offset` | Отступ SL от средней цены после 2-го ордера | 2% |
| `use_trailing` / `trailing_percent` | Trailing stop | true / 1.5% |

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

**Пример:** депозит $1000, BTC/USDT LONG, вход $50,000.
1. Ордер #1: $250 @ $50,000, SL = $47,500 (-5%)
2. Цена → $52,000 (+4%): ордер #2 $375, avg = $51,200, новый SL = $52,224 (уже в прибыли)
3. Цена → $54,080 (+4% от $52k): ордер #3 $562.5, avg = $52,640, новый SL = $53,693
4. Разворот и касание SL → закрытие всей позиции с прибылью

## Разработка

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install && npm run dev

# Миграции backend
cd backend
alembic revision --autogenerate -m "..."
alembic upgrade head
```

## State Machine бота

```
IDLE → WAITING → ENTRY → PYRAMIDING → EXIT
  ↑                                    │
  └────────────────────────────────────┘
```
- **IDLE** — бот создан, ждёт ручного действия
- **WAITING** — задана лимитная цена входа, ждёт её достижения
- **ENTRY** — первый ордер размещён
- **PYRAMIDING** — активны доборы при движении цены
- **EXIT** — позиция закрыта (SL / ручное закрытие)

## Что система делает / не делает

✅ Риск-менеджмент через среднюю цену позиции, trend-pyramiding, dynamic SL, live-мониторинг, multi-account
❌ Автоматические торговые сигналы для входа (сигналы из `services/signals` — информационные, автотрейдинга по ним нет), усреднение убытка (мартингейл) в pyramiding-ботах, HFT/арбитраж

## Troubleshooting

**Backend не запускается** — `docker compose ps`, `docker compose logs backend` (проверить Postgres/Redis healthy).

**Пирамидинг не срабатывает** — проверить, доходят ли тики цены: в логах backend искать `[TICK]`, `[AVG TRIGGER]`; в логах `price-tracker` — реально ли стримится символ (`GET /subscriptions` на price-tracker); частая причина — сбой HTTP-вызова backend → price-tracker при регистрации стратегии (см. `_notify_price_tracker` в `backend/app/services/websocket.py`).

**Frontend не подключается к API** — проверить `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_SIGNALS_URL`, `NEXT_PUBLIC_BACKTESTER_URL` в `.env`.

## Технологии

**Backend:** FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis 7, pybit, aiohttp
**Frontend:** Next.js 14, TypeScript, Tailwind CSS, TanStack Query, Zustand
**Backtester:** Flask, CCXT, `ta` (индикаторы)
**Инфраструктура:** Docker Compose, Grafana + Loki + Promtail (логи), GitHub Actions (независимый CI/CD на каждый сервис)

## Документация по модулям

- [`services/backtester/README.md`](services/backtester/README.md) — бэктестер: CLI, конфиги, стратегии
- [`services/backtester/README_PINE_STRATEGY.md`](services/backtester/README_PINE_STRATEGY.md) — standalone TradingView Pine-стратегия
- [`services/backtester/migrations/README.md`](services/backtester/migrations/README.md) — миграции БД бэктестера
