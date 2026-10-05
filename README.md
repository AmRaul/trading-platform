# Trading Platform — Trend Pyramiding + Multi-Service Backend

Торговая платформа для управления позициями на крипто-фьючерсах со стратегией **trend pyramiding** (доборы только в прибыль, без усреднения убытка) и многоступенчатым **Stop Loss** (начальный → безубыток → от средней цены + trailing). Помимо основного торгового движка включает отдельные сервисы для скринера рынка/трендовых сигналов и бэктестинга стратегий на исторических данных.

## Основная концепция: Trend Pyramiding

Риск не фиксируется на входе, а управляется через среднюю цену позиции и динамический стоп-лосс.

1. **Вход** — ручной, по лимитной цене (`WAITING` → бот ждёт указанную цену, затем открывает позицию) или по сигналу MRC (`SIGNAL` → бот ждёт сигнал на закрытии свечи, см. `entry_signal`)
2. **Пирамидинг** — при движении цены на `step_percent` от последнего ордера в прибыльную сторону добавляется новый ордер размером `предыдущий × pyramiding_multiplier`, максимум `order_count` ордеров. Доборы **только в прибыль** — усреднение убытка (мартингейл) исключено намеренно.
3. **Stop Loss по стадиям** (пересчитывается после каждого ордера и отправляется на биржу):
   - **ордер #1** — `sl_initial` от цены входа (можно отключить: `null` → стоп не ставится вообще);
   - **ордер #2** — перенос в безубыток: `avg_price ± sl_breakeven_plus` на стороне прибыли (если `sl_breakeven_on_order2 = true`; иначе остаётся `sl_initial`);
   - **ордер #3+** — `avg_price ∓ sl_after_order3` от средней цены позиции (работает независимо от `sl_initial`).
4. **Trailing Stop** (опционально) — тянется за ценой, итоговый SL = `max(stage_SL, trailing_SL)` для LONG (`min` для SHORT).
5. **Take Profit** — `tp_percent` ставится только вместе с последним (`order_count`-м) добором; до этого позиция сопровождается только стопом. У DCA-ботов TP ставится сразу при входе и пересчитывается от средней после каждого страховочного. TP и SL backend отслеживает и сам по цене — сделка закрывается у нас, даже если её уже закрыл биржевой тейк/стоп.
6. **Выход** — по SL/TP, ручным закрытием из UI (с подтверждением). При `cycle = true` бот сразу открывает новую позицию после закрытия.

Исполнение сделок — через **Cryptorg** (webhook API) или напрямую через **Bybit** (Unified Trading API, ключи пользователя), биржа выбирается на уровне бота. Live-цены в любом случае идут из публичных WebSocket-тикеров Bybit через `price-tracker`.

## Архитектура

Это монорепозиторий из независимо разворачиваемых сервисов — у каждого своя БД (кроме price-tracker, который БД не использует) и свой CI/CD pipeline.

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────────┐
│  Next.js UI  │────▶│  backend/         │────▶│ Cryptorg webhook │
│  (frontend)  │     │  Execution Service│     │ или Bybit API    │
└──────┬───────┘     │  (FastAPI)        │     │  (исполнение)    │
       │             └────┬──────────┬───┘     └──────────────────┘
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

Основной торговый движок (FastAPI + SQLAlchemy async). Владеет пользователями, ботами, позициями, ордерами, сделками, Cryptorg- и Bybit-аккаунтами.

- **Боты** — `Bot` с состояниями `IDLE → WAITING → ENTRY → PYRAMIDING → EXIT`, конфигурация стратегии хранится в JSON-колонке `config` (см. [Конфигурация стратегии](#конфигурация-стратегии))
- **Биржа исполнения** — поле `exchange` у бота: `cryptorg` (по умолчанию) или `bybit`. Обе реализуют порт `ExchangeExecutor` (`adapters/cryptorg_executor.py`, `adapters/bybit_executor.py`). Cryptorg принимает SL/TP в процентах прямо в webhook; Bybit требует абсолютные цены, поэтому ордер ставится без SL/TP, затем по фактической `avgPrice` вторым вызовом выставляется `set_trading_stop`
- **Multi-account** — у пользователя может быть несколько `CryptorgAccount` (webhook URL/ключи) и `BybitAccount` (API key/secret, флаг `testnet`); каждый бот привязывается к конкретному аккаунту. Ключи Bybit хранятся зашифрованными (`ENCRYPTION_KEY`), в API отдаётся только хвост ключа
- **DCA vs Pyramiding боты** — оба типа ведёт backend одинаково для любой биржи через порт `ExchangeExecutor`: `bot_type: "pyramiding"` — доборы в прибыль, `bot_type: "dca"` — страховочные в просадку (шаг от предыдущего ордера, рыночный ордер при касании уровня). Нативный DCA Cryptorg не используется
- **Сверка с биржей** — раз в минуту `get_open_position_size`: если позиции на бирже нет (ручное закрытие, ликвидация), сделка закрывается у нас как `EXCHANGE_CLOSED`. Bybit — через `get_positions`; Cryptorg Ghost Bot API позиции не отдаёт, там работает только отслеживание TP/SL по цене
- **Realtime** — `price_stream_manager` слушает Redis pub/sub от price-tracker и прогоняет каждый тик через `StrategyEngine.on_price_update()`; при рестарте `restore_active_strategies()` заново поднимает активные стратегии из БД
- Слоистая архитектура: `api/routes` (HTTP) → `services/strategy.py` (оркестратор) → `application/trading/*` (use cases: open/close/add pyramiding order) → `domain/trading/*` (чистая логика расчётов)

Основные группы роутов (`backend/app/api/routes/`): `auth`, `bots`, `trading` (вход/выход/лимитные ордера), `positions`, `trades`, `accounts` (Cryptorg-аккаунты), `bybit-accounts` (Bybit-аккаунты), `admin` (статистика, пользователи, все боты, health-check сервисов — доступ только для `ADMIN_USERNAME`), `ready-strategies` (каталог готовых стратегий из `domain/ready_strategies/catalog.py` с вариантами риска, результаты бэктеста — JSON, генерируемый `services/backtester/research/`; `POST /{slug}/launch` — запуск в один клик: бот из пресета варианта, первый ордер = депозит × % варианта, сразу в состоянии `SIGNAL`), `websocket` (`/api/ws` — live цены/PnL/SL). Файлы `profile.py`, `signals.py`, `trend_signals.py` — устаревшие и в `main.py` не подключены (функциональность перенесена в `accounts`/`bybit-accounts` и `services/signals`).

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
| `ready-strategies` | Каталог готовых стратегий: описание, правила, варианты риска, бэктест (equity, метрики по годам), запуск в один клик (биржа, аккаунт, депозит) |
| `bots` | CRUD ботов, ручной вход/выход, лимитный вход, конфиг стратегии, привязка аккаунта |
| `positions` | Live-мониторинг открытых позиций (цена, avg price, SL, unrealized PnL) |
| `history` | История закрытых сделок, win rate |
| `accounts` | CRUD Cryptorg-аккаунтов (multi-account) |
| `bybit-accounts` | CRUD Bybit-аккаунтов (API key/secret, testnet) |
| `admin`, `admin/users`, `admin/bots`, `admin/health` | Админка: общая статистика, пользователи, все боты, состояние сервисов |
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

Обязательно задать в `.env`: `SECRET_KEY`, `ENCRYPTION_KEY` (Fernet-ключ для шифрования API-ключей Bybit, команда генерации — в `.env.example`), `ADMIN_USERNAME` (логин, которому доступна админка; пусто — админка закрыта для всех).

Первый запуск: зарегистрироваться → создать аккаунт биржи (Accounts для Cryptorg или Bybit Accounts) → создать бота (Bots), выбрать биржу и аккаунт → задать конфиг стратегии → войти в позицию.

## Конфигурация стратегии

Схема — `StrategyConfig` в `backend/app/schemas/bot.py`.

| Параметр | Описание | По умолчанию |
|---|---|---|
| `bot_type` | `pyramiding` (доборы в прибыль) или `dca` (страховочные в просадку); оба ведёт backend | `pyramiding` |
| `order_count` | Максимум ордеров (вход + доборы/страховочные), 1–10 | 4 |
| `entry_size_usdt` | Размер первого ордера, USDT (мин. 10) | 10 |
| `step_percent` | Шаг цены от последнего ордера для добора (мин. 0.5%) | 4% |
| `leverage` | Плечо | 10 |
| `pyramiding_multiplier` | Размер добора = предыдущий × множитель (`<1` — уменьшающиеся доборы) | 1.5 |
| `sl_initial` | SL первого ордера от цены входа; `null` — без стопа | 5% |
| `sl_breakeven_on_order2` | Переносить SL в безубыток после 2-го ордера | true |
| `sl_breakeven_plus` | Отступ безубыточного стопа от средней цены в сторону прибыли | 0.5% |
| `sl_after_order3` | Отступ SL от средней цены начиная с 3-го ордера | 2% |
| `use_trailing` / `trailing_percent` | Trailing stop (мин. 0.5%) | true / 1.5% |
| `tp_percent` | Take profit: для pyramiding — только на последнем ордере, для DCA — сразу | 3% |
| `cycle` | Автоматически открывать новую позицию после закрытия (с `entry_signal` — снова ждать сигнал) | false |
| `entry_signal` | Вход по сигналу вместо ручного/лимитного: MRC на `timeframe` (полоса `entry_band`) + фильтр тренда `trend_ema_period` на `trend_timeframe`. Бот в состоянии `SIGNAL`, проверку делает `services/signal_scheduler.py` на закрытии каждой свечи; `null` — выкл | null |
| `dca_multiplier` / `dca_multiplier_price` | Только для DCA: множитель объёма следующего ордера, множитель шага цены для каждого следующего уровня | 1.0 / 1.0 |
| `sl_initial` (DCA) | Для DCA — стоп от средней цены, включается только после заполнения всей сетки | 5% |

```json
{
  "bot_type": "pyramiding",
  "order_count": 4,
  "entry_size_usdt": 100,
  "step_percent": 4.0,
  "leverage": 10,
  "pyramiding_multiplier": 1.5,
  "sl_initial": 5.0,
  "sl_breakeven_on_order2": true,
  "sl_breakeven_plus": 0.5,
  "sl_after_order3": 2.0,
  "use_trailing": true,
  "trailing_percent": 1.5,
  "tp_percent": 3.0,
  "cycle": false
}
```

**Пример** (конфиг выше, BTC/USDT LONG, вход $50,000, без учёта trailing):
1. Ордер #1: $100 @ $50,000 → SL = $47,500 (−5% от входа)
2. Цена → $52,000 (+4%): ордер #2 $150, avg = $51,200 → SL в безубыток = $51,456 (avg +0.5%)
3. Цена → $54,080: ордер #3 $225, avg ≈ $52,564 → SL ≈ $51,513 (avg −2%)
4. Цена → $56,243: ордер #4 $337.5 (последний), avg ≈ $54,092 → SL ≈ $53,011, на бирже выставляется TP +3%
5. Позиция закрывается по TP, SL (с прибылью) или вручную

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
- **EXIT** — позиция закрыта (SL / TP / ручное закрытие); при `cycle = true` бот сразу заходит заново

## Что система делает / не делает

✅ Риск-менеджмент через среднюю цену позиции, trend-pyramiding, стадийный SL (безубыток/от средней/trailing), TP, live-мониторинг, multi-account, две биржи исполнения (Cryptorg, Bybit)
❌ Автоматические торговые сигналы для входа (сигналы из `services/signals` — информационные, автотрейдинга по ним нет), усреднение убытка (мартингейл) в pyramiding-ботах, HFT/арбитраж

## Troubleshooting

**Backend не запускается** — `docker compose ps`, `docker compose logs backend` (проверить Postgres/Redis healthy). Состояние сервисов также видно на странице `admin/health`.

**Bybit-бот не открывает позицию** — проверить, что у бота выбран `bybit_account_id`, ключи имеют торговые права для Unified/linear, а флаг `testnet` совпадает с типом ключей; в логах backend искать `[Bybit]`.

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
