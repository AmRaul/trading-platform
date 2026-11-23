# Trading Platform — Trend Pyramiding + Multi-Service Backend

Торговая платформа для управления позициями на крипто-фьючерсах со стратегией **trend pyramiding** (доборы только в прибыль, без усреднения убытка) и многоступенчатым **Stop Loss** (начальный → безубыток → от средней цены + trailing). Помимо основного торгового движка включает отдельные сервисы для скринера рынка/трендовых сигналов и бэктестинга стратегий на исторических данных.

## Основная концепция: Trend Pyramiding

Риск не фиксируется на входе, а управляется через среднюю цену позиции и динамический стоп-лосс.

1. **Вход** — ручной, по лимитной цене (`WAITING` → бот ждёт указанную цену, затем открывает позицию) или по сигналу индикатора — MRC или разворот Supertrend с фильтром тренда (`SIGNAL` → бот ждёт сигнал на закрытии свечи, см. `entry_signal`)
2. **Пирамидинг** — при движении цены на `step_percent` от последнего ордера в прибыльную сторону добавляется новый ордер размером `предыдущий × pyramiding_multiplier`, максимум `order_count` ордеров. Доборы **только в прибыль** — усреднение убытка (мартингейл) исключено намеренно.
3. **Stop Loss по стадиям** (пересчитывается после каждого ордера и отправляется на биржу):
   - **ордер #1** — `sl_initial` от цены входа (можно отключить: `null` → стоп не ставится вообще);
   - **ордер #2** — перенос в безубыток: `avg_price ± sl_breakeven_plus` на стороне прибыли (если `sl_breakeven_on_order2 = true`; иначе остаётся `sl_initial`);
   - **ордер #3+** — `avg_price ∓ sl_after_order3` от средней цены позиции (работает независимо от `sl_initial`).
4. **Trailing Stop** (опционально) — тянется за ценой, итоговый SL = `max(stage_SL, trailing_SL)` для LONG (`min` для SHORT).
5. **Take Profit** — `tp_percent` ставится только вместе с последним (`order_count`-м) добором; до этого позиция сопровождается только стопом. У DCA-ботов TP ставится сразу при входе и пересчитывается от средней после каждого страховочного. TP и SL backend отслеживает и сам по цене — сделка закрывается у нас, даже если её уже закрыл биржевой тейк/стоп.
6. **Выход** — по SL/TP, ручным закрытием из UI (с подтверждением). При `cycle = true` бот сразу открывает новую позицию после закрытия.

Кроме пирамидинга есть **DCA** (страховочные в просадку) и **straddle** (пара LONG+SHORT с добором в рабочую сторону, `TODO/6`).

**Площадка исполнения** выбирается на уровне бота:
- **Cryptorg** — основная для реальных денег. Команды — webhook Ghost Bot, проверка исполнения — API Bybit через ключ «только чтение» счёта Cryptorg «Bybit-ликвидность» (см. [Cryptorg](#cryptorg-webhook--проверка-через-bybit));
- **Bybit** — напрямую через Unified Trading API, ключи пользователя (второстепенная, на реальном счёте ещё не проверялась);
- **paper** — бумажный режим: живые цены Bybit, ордера никуда не уходят, комиссия taker 0.055% вычитается из PnL. На нём идёт форвард-тест портфеля (`TODO/7`).

Live-цены в любом случае идут из публичных WebSocket-тикеров Bybit через `price-tracker`.

## Архитектура

Монорепозиторий из сервисов в одном `docker-compose.yml`; у каждого сервиса своя БД (price-tracker, alerter и MCP БД не используют). Снаружи — nginx на VPS (`deploy/nginx`).

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────────────────┐
│  Next.js UI  │────▶│  backend/         │────▶│ Cryptorg webhook (команды)│
│  (frontend)  │     │  Execution Service│     │ Bybit API (Bybit; чтение │
└──────┬───────┘     │  (FastAPI)        │     │  позиций для Cryptorg)   │
       │             └──┬────┬──────┬────┘     └──────────────────────────┘
       │                │    │      │
       │        Redis pub/sub│   Postgres (trading_db)
       │                │    │      │
       │                ▼    │      └──────▶ services/backup → Telegram-канал (шифрованный дамп)
       │   ┌───────────────┐ │
       │   │ price-tracker │─┼────▶ Bybit WS (цены)
       │   └───────────────┘ │
       │                     ├◀──── services/alerter (health → Telegram)
       │                     └◀──── services/mcp (kandle MCP для Claude)
       │
       ├────────▶ services/signals (скринер, тренд-сигналы) — своя БД (signals_db)
       │
       └────────▶ services/backtester (бэктест стратегий) — своя БД (backtester)
```

Frontend обращается к трём backend-URL напрямую из браузера (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SIGNALS_URL`, `NEXT_PUBLIC_BACKTESTER_URL`). Сервисы друг про друга не знают, кроме backend ↔ price-tracker (Redis) и alerter/MCP → backend (HTTP API). `signals.` и `backtester.` закрыты nginx `auth_request` — нужен вход в kandle.

### backend/ — Execution Service

Основной торговый движок (FastAPI + SQLAlchemy async). Владеет пользователями, ботами, позициями, ордерами, сделками, Cryptorg- и Bybit-аккаунтами.

- **Боты** — `Bot` с состояниями `IDLE / WAITING / SIGNAL → PYRAMIDING → IDLE` (straddle — `STRADDLE`), конфигурация стратегии хранится в JSON-колонке `config` (см. [Конфигурация стратегии](#конфигурация-стратегии))
- **Площадка исполнения** — поле `exchange` у бота: `cryptorg` (по умолчанию), `bybit` или `paper`. Все реализуют порт `ExchangeExecutor` (`adapters/cryptorg_executor.py`, `adapters/bybit_executor.py`, `adapters/paper_executor.py`), выбор — `adapters/executor_factory.py`. Cryptorg принимает SL/TP в процентах прямо в webhook; Bybit требует абсолютные цены, поэтому ордер ставится без SL/TP, затем по фактической `avgPrice` вторым вызовом выставляется `set_trading_stop`
- **Multi-account** — у пользователя может быть несколько `CryptorgAccount` (webhook URL + ключ Bybit для сверки) и `BybitAccount` (API key/secret, флаг `testnet`); каждый бот привязывается к конкретному аккаунту. Ключи и webhook хранятся зашифрованными (`ENCRYPTION_KEY`), в API отдаётся только хвост
- **Типы ботов** — все ведёт backend одинаково для любой площадки через порт `ExchangeExecutor`: `pyramiding` — доборы в прибыль, `dca` — страховочные в просадку (шаг от предыдущего ордера, рыночный ордер при касании уровня; нативный DCA Cryptorg не используется), `straddle` — пара LONG+SHORT (`services/straddle_runner.py`, `domain/trading/straddle.py`; Bybit — в режиме хеджа)
- **Вход по сигналу** — `services/signal_scheduler.py` на закрытии каждой свечи сигнального ТФ проверяет ботов в `SIGNAL` (MRC или Supertrend + фильтр тренда EMA)
- **Сверка с биржей** — раз в минуту `get_open_position_size`: если позиции на бирже нет (ручное закрытие, ликвидация, биржевой стоп), сделка закрывается у нас как `EXCHANGE_CLOSED`. Bybit и Cryptorg с ключом — через `get_positions` Bybit; paper и Cryptorg без ключа не сверяются
- **Неподтверждённое закрытие** — если биржа говорит, что позиция ещё открыта, сделка у нас не закрывается: бот повторяет закрытие каждые 15 с (даже если цена вернулась — выход уже решён) и до тех пор ничего не добирает. Неисполненный добор повторяется не раньше чем через 60 с
- **Позиция-сирота** (`services/exchange_watch.py`) — раз в 2 мин для реальных ботов без позиции читается биржа; позиция без бота, увиденная две проверки подряд, — проблема в bots-health. Сторож ничего не закрывает
- **Проблемы исполнения → Telegram** — неподтверждённые вход/добор/закрытие и сироты попадают в `issues` `/api/analytics/bots-health` (`services/exchange_issues.py`), alerter шлёт их в Telegram
- **Уведомления о сделках → личный Telegram** (`services/telegram_notifier.py`) — вход, добор, выход (с PnL и причиной), конец straddle, в момент события, в чат **владельца бота**; бумажные помечены 📝. Отправка отдельной задачей — торговый цикл её не ждёт. Пользователь привязывает чат в «Настройках» (одноразовая ссылка `t.me/<бот>?start=<код>`, `services/telegram_bot.py` читает `/start` и `/stop`) и выбирает режим: все / только реальные / выключено. Владелец платформы, пока не привязал свой чат, получает в `TELEGRAM_CHAT_ID`. `TELEGRAM_NOTIFY=off|real` — глобально
- **Личные алерты** (`services/user_alerts.py`) — раз в 5 мин bots-health каждого пользователя с привязанным Telegram → в его чат: проблема появилась / ушла / держится. Владельца и сам бэкенд сторожит `services/alerter`
- **Пользователи** — регистрация ждёт одобрения админа (заявка приходит владельцу в Telegram, одобрить/отклонить — `admin/users`); админ может заблокировать (токены перестают действовать сразу, боты продолжают работать) и сбросить пароль (временный показывается один раз). Смена пароля — «Настройки». Вход: 10 неудачных попыток за 15 мин с одного IP на логин → 429. Лимит ботов — `MAX_BOTS_PER_USER` (20), у админа без лимита
- **Realtime** — `price_stream_manager` слушает Redis pub/sub от price-tracker и раздаёт цены ботам. У каждого бота своя очередь (`EngineWorker`): бот, ждущий биржу, не задерживает стопы остальных; пока он занят, промежуточные цены заменяются последней. При обрыве Redis слушатель переподключается и переподписывается; при рестарте `restore_active_strategies()` поднимает активные стратегии из БД
- **Сессии БД** — движок бота живёт днями, но соединение с БД не держит: каждая операция (вход, добор, закрытие, шаг straddle) открывает свою сессию; тик без событий базу не трогает. Проверяется интеграционным тестом на настоящем Postgres (`backend/integration/engine_session.py`, в CI)
- **Авторизация** — access-токен JWT на 30 мин (только в памяти вкладки) + refresh-токен на 30 дней в httpOnly-cookie `kandle_refresh` (`POST /api/auth/refresh`, ротация при каждом обновлении). Смена пароля отзывает все refresh-токены. WebSocket `/api/ws` требует первым сообщением `{"type":"auth","token":...}` (иначе закрытие с кодом 4401); события бота уходят только его владельцу
- **Health** — `GET /health` честный: БД, Redis, планировщик сигналов, поток цен; при сбое — 503. `GET /api/analytics/bots-health` — по каждому боту: идут ли тики, проверяется ли сигнал, проблемы исполнения
- Слоистая архитектура: `api/routes` (HTTP) → `services/strategy.py` (оркестратор) → `application/trading/*` (use cases: open/close/add order) → `domain/trading/*` (чистая логика расчётов)

Основные группы роутов (`backend/app/api/routes/`): `auth` (вход, заявка на регистрацию, refresh, смена пароля), `me` (профиль, личный Telegram, лимит ботов), `bots`, `trading` (вход/выход/лимитные ордера), `positions`, `trades`, `accounts` (Cryptorg-аккаунты, `POST /{id}/check` — проверка ключа Bybit, `GET /{id}/exchange` — счёт глазами биржи), `bybit-accounts` (Bybit-аккаунты), `analytics` (bots-health, контекст рынка, сделки, сверка с бэктестом, журнал разборов, `changes` — что изменилось с прошлой проверки, `forward-test` — комплекты форвард-теста, `position-levels/{bot_id}` — уровни позиции; API под kandle MCP), `admin` (статистика, пользователи — одобрить / заблокировать / сбросить пароль, все боты, health-check сервисов — доступ только для `ADMIN_USERNAME`), `ready-strategies` (каталог готовых стратегий из `domain/ready_strategies/catalog.py` с вариантами риска, результаты бэктеста — JSON, генерируемый `services/backtester/research/`; `POST /{slug}/launch` — запуск в один клик: бот из пресета варианта, первый ордер = депозит × % варианта, сразу в состоянии `SIGNAL`), `websocket` (`/api/ws` — live цены/PnL/SL). Файлы `profile.py`, `signals.py`, `trend_signals.py` — устаревшие и в `main.py` не подключены.

#### Cryptorg: webhook + проверка через Bybit

Своего API для сделок у Cryptorg нет: webhook Ghost Bot (`open` / `average` / `update` / `close`) только принимает команды и не сообщает, исполнилась ли команда и по какой цене. Счёт Cryptorg «Bybit-ликвидность» — субаккаунт Bybit, и его API-ключ работает с API самого Bybit. Поэтому в аккаунте Cryptorg два разных доступа:

| | Для чего | Где взять |
|---|---|---|
| **Webhook URL** | открывать, добирать, закрывать сделки | настройки Crazy-бота в Cryptorg |
| **Bybit API key/secret, «Только чтение»** | видеть позицию на бирже и подтверждать команды | Cryptorg → счёт «Bybit-ликвидность» → API-ключи (права «Позиция на фьючерсах», «Ордер на фьючерсах»; лучше с ограничением по IP — ключ без него отключается через 90 дней) |

С ключом `CryptorgExecutorAdapter` подтверждает каждую команду позицией на бирже (ждёт до 20 с):
- **вход** — на бирже не должно быть позиции этой монеты и стороны (иначе Ghost Bot усреднил бы её), после команды позиция должна появиться; цена входа — фактическая средняя;
- **добор** — размер должен вырасти; цена добора — из прироста стоимости позиции;
- **закрытие** — успех, только когда позиции не осталось;
- **webhook ответил ошибкой, а позиция на бирже есть** — это исполнение, второй вход бот не откроет.

Без ключа Cryptorg работает вслепую: ответ 200 считается исполнением, сверки нет (пометка в bots-health). Кнопка «Проверить ключ» на странице `accounts` показывает, работает ли ключ, только ли чтение и какие позиции видны. Страница **«Счёт»** (`accounts/{id}`) — все открытые позиции и закрытые сделки счёта за 7/30/90 дней (closed PnL Bybit), включая ручные и других ботов Cryptorg, с пометкой, какой бот вёл сделку. Только просмотр.

Ключ видит **все** позиции счёта, включая ручные. Ручная позиция на той же монете и стороне, что и бот без позиции, заблокирует вход бота и через ~4 мин даст алерт «позиция без бота». Ручную торговлю лучше вести на отдельном счёте Bybit-ликвидности. В настройках бота Cryptorg выключить «Открывать сделки в непрерывном режиме».

### services/price-tracker/

Отдельный лёгкий FastAPI-сервис: держит WebSocket-подключения к Bybit (`pybit`, публичные ticker-стримы) и публикует цены в Redis pub/sub. Backend подписывается на нужные символы через внутренний HTTP API (`POST/DELETE /subscribe`) при регистрации/снятии стратегии бота. Работает только внутри docker-сети, наружу порт не пробрасывается.

### services/signals/

Независимый сервис (своя БД `signals_db`), не связан с backend напрямую — фронтенд обращается к нему отдельно. Два фоновых сканера:
- **Screener** — раз в 15 минут сканирует весь рынок, классифицирует по Vol 1h + Range% (PUMPING/DUMPING/COOLING)
- **Trend** — отслеживает тренд (EMA21 4h/1h) по настраиваемому watch-list символов (по умолчанию альты с объёмом: SOL, AVAX, LINK, ETH, BNB, DOT, AAVE)
- **Signal strategies** — настраиваемые правила детекции (встроенные: MOMENTUM, REVERSAL, BREAKOUT)

### services/backtester/

Отдельное Flask-приложение с CLI и веб-UI для бэктестинга стратегий (Long/Short DCA + martingale, EMA/RSI/ADX-фильтры, MRC — Mean Reversion Channel) на исторической OHLCV-истории через CCXT. Своя БД (`backtester`), свои миграции. Встроен также как страница внутри основного Next.js-фронтенда (`frontend/app/backtester`). Подробнее — `services/backtester/README.md`. В compose ограничен (1 ядро, 1.5 ГБ, низкий приоритет CPU), чтобы тяжёлый бэктест не тормозил ботов. **Гипотезы** (`hypothesis_runner.py`, `/api/research/*`): вариации готовых стратегий (шорт альтов, MRC DCA) против базы на тех же данных — тот же исследовательский движок (`research/`, у шорта — `PositionCalculator` бота), меняются только параметры из белого списка, комиссия и funding всегда; нет истории на сервере — скачивается 15m с Bybit. Журнал и правила — в бэкенде (`api/routes/research.py`, таблица `hypotheses`): гипотеза и критерий до прогона, сначала только обучающий период (2021-01 → 2024-07), отложенный (2024-07 → 2026-10) — один раз после решения, счётчик попыток идеи, не больше 3 прогонов одновременно и 20 в сутки. Образ собирается из корня репозитория (`Dockerfile.web` + `Dockerfile.web.dockerignore`) — в нём `backend/app/domain/trading`. Бэктесты идут через очередь (`backtest_queue.py`): по одному за раз (`BACKTEST_MAX_PARALLEL`), скачивание данных — до двух (`DOWNLOAD_MAX_PARALLEL`), остальные ждут по порядку, место в очереди видно в статусе; оптимизации — своя очередь, по одной. Redis не нужен: бэктестер — один процесс.

### services/alerter/

Отдельный контейнер, который пишет в Telegram, когда торговая система перестаёт работать как должна: раз в 5 мин опрашивает `GET /health` и `/api/analytics/bots-health`. Сообщает, когда проблема появилась, когда ушла, и напоминает, если держится 6 ч; недоступность бэкенда — только после 2 проверок подряд (рестарт при деплое — не тревога). Отдельно от бэкенда, чтобы не падать вместе с ним. Переменные: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, логин kandle.

### services/backup/

Ежедневно в 03:00 UTC: `pg_dump` баз `trading_db` и `signals_db` → шифрование AES-256 (`BACKUP_PASSPHRASE`) → проверка (расшифровка + чтение всего архива `pg_restore`) → отправка в приватный Telegram-канал (`TELEGRAM_BACKUP_CHAT_ID`), файлы больше 45 МБ — частями. 7 последних копий остаются на сервере. Неудача — сообщение в чат алертов. Ручной запуск: `docker exec trading_backup python backup.py now`. Восстановление — `services/backup/README.md`. **`BACKUP_PASSPHRASE` хранить и вне GitHub** — без неё бэкапы не расшифровать.

### services/mcp/

kandle MCP — сервер Model Context Protocol поверх `/api/analytics`: Claude (CLI, claude.ai, мобильный — через `kandle.tech/mcp/<token>`) видит ботов, сделки, контекст рынка и позиции, ведёт журнал разборов (health_check, monthly_review, second_opinion). `what_changed` — что изменилось с прошлой проверки (снимки состояния в `state_snapshots`), `forward_test_sets` — комплекты форвард-теста с ожиданиями, `reconcile_trades` — сверка всех сделок периода с бэктестом одной сводкой, журнал гипотез (`research_bases`, `hypothesis_test`, `hypothesis_status`, `hypothesis_reveal`, `hypotheses_list`, prompt `test_hypothesis`) — проверка идей бэктестом с телефона, `account_overview` — счёт Cryptorg (все позиции и сделки, включая ручные), `get_position_context` — с уровнями позиции (результат на стопе/тейке с комиссией, когда трейлинг двинет стоп, следующий ордер). Бумажных ботов форвард-теста MCP не трогает.

**Комплекты форвард-теста** — поле бота `forward_test` (`portfolio/mrc`, `portfolio/short`, `take6/short`); ожидания и критерии остановки — `backend/app/domain/forward_test.py` (цифры из `TODO/7`, записаны до старта). Переименование бота разбор не ломает. Подробнее — `services/mcp/README.md`, планы — `TODO/8`.

## Frontend

Next.js 14 (App Router) + TypeScript + Tailwind + TanStack Query.

| Страница | Назначение |
|---|---|
| `dashboard` | Обзор: активные боты, суммарный PnL, открытые позиции |
| `ready-strategies` | Каталог готовых стратегий: описание, правила, варианты риска, бэктест (equity, метрики по годам), запуск в один клик (биржа, аккаунт, депозит) |
| `bots` | Боты по вкладкам площадок (Cryptorg / Bybit / бумажные) и группам стратегий: CRUD, ручной вход/выход, лимитный вход и вход по сигналу, конфиг, straddle-панель |
| `positions` | Live-мониторинг открытых позиций (цена, avg price, SL, unrealized PnL) |
| `history` | История закрытых сделок, win rate |
| `accounts` | Cryptorg-аккаунты: webhook URL, ключ Bybit для сверки, «Проверить ключ» |
| `accounts/[id]` | Счёт Cryptorg на бирже: все позиции и закрытые сделки (включая ручные), кто их вёл |
| `bybit-accounts` | CRUD Bybit-аккаунтов (API key/secret, testnet) |
| `admin`, `admin/users`, `admin/bots`, `admin/health` | Админка: общая статистика, пользователи (заявки, блокировка, сброс пароля), все боты, состояние сервисов |
| `settings` | Настройки: личный Telegram (подключить, что присылать), смена пароля, лимит ботов |
| `screener` | Кандидаты со скринера (`services/signals`) |
| `signals` / `trend-signals` | Залогированные сигналы скринера / тренд-детектора |
| `signal-strategies` | CRUD правил детекции сигналов |
| `trend-symbols` | Watch-list символов для тренд-сканера |
| `backtester` | Запуск и мониторинг бэктестов |
| `login` | Вход / заявка на регистрацию |

## Быстрый старт (docker compose)

```bash
cp .env.example .env    # заполнить секреты
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API + Swagger: http://localhost:8000/docs
- Signals API: http://localhost:8020
- Grafana (логи, если поднят стек мониторинга): см. `docker-compose.yml`

Обязательно задать в `.env`: `SECRET_KEY`, `ENCRYPTION_KEY` (Fernet-ключ для шифрования ключей и webhook, команда генерации — в `.env.example`), `ADMIN_USERNAME` (логин, которому доступна админка; пусто — админка закрыта для всех). Для алертов и бэкапов: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_BACKUP_CHAT_ID`, `BACKUP_PASSPHRASE`.

Первый запуск: зарегистрироваться → создать аккаунт (Accounts — Cryptorg: webhook + ключ Bybit «только чтение»; или Bybit Accounts) → создать бота (Bots), выбрать площадку и аккаунт (или `paper` без аккаунта) → задать конфиг стратегии → войти в позицию. Либо запустить готовую стратегию в один клик (`ready-strategies`).

## Деплой

`.github/workflows/deploy.yml` на push в `main`: тесты (backend + интеграционный тест на Postgres, индикаторы backtester, signals, price-tracker, alerter, backup, MCP) → сборка образов в GHCR (включая фронтенд) → деплой на VPS по SSH, `.env` собирается из GitHub Secrets. Если упал хоть один тест — сборки и деплоя нет. Секреты и первичная настройка сервера — `deploy/README.md`.

## Конфигурация стратегии

Схема — `StrategyConfig` в `backend/app/schemas/bot.py`.

| Параметр | Описание | По умолчанию |
|---|---|---|
| `bot_type` | `pyramiding` (доборы в прибыль), `dca` (страховочные в просадку) или `straddle` (пара LONG+SHORT, сторона бота `NEUTRAL`, только ручной запуск) | `pyramiding` |
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
| `entry_signal` | Вход по сигналу вместо ручного/лимитного. `type: mrc` — цена в полосе MRC (`entry_band`) на `timeframe`; `type: supertrend` — разворот Supertrend (`st_period`, `st_mult`) в сторону сделки; `type: donchian` — close свечи `timeframe` выше максимума `donchian_entry_days` закрытых дневок (SHORT — ниже минимума), и **выход по сигналу**: в позиции планировщик на закрытии каждой свечи проверяет close ниже минимума `donchian_exit_days` дневок и закрывает по рынку (`SIGNAL_EXIT`), фильтр тренда не используется. Для mrc/supertrend — фильтр тренда: close относительно EMA `trend_ema_period` на `trend_timeframe` (опционально `trend_ema_fast` выше/ниже неё). Бот в состоянии `SIGNAL`, проверку делает `services/signal_scheduler.py` на закрытии каждой свечи; `null` — выкл | null |
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
IDLE ──(лимит)──▶ WAITING ──┐
  │                         ├──▶ PYRAMIDING ──(SL / TP / вручную / EXCHANGE_CLOSED)──▶ IDLE или SIGNAL
  └──(сигнал)───▶ SIGNAL ───┘
```
- **IDLE** — бот создан или позиция закрыта, ждёт ручного действия
- **WAITING** — задана лимитная цена входа, ждёт её достижения
- **SIGNAL** — ждёт сигнал `entry_signal` на закрытии свечи
- **PYRAMIDING** — позиция открыта: стоп, тейк, доборы/страховочные
- **STRADDLE** — запущена пара LONG+SHORT (`bot_type: straddle`)

После закрытия при `cycle = true` бот с `entry_signal` снова ждёт сигнал (`SIGNAL`), без сигнала — сразу открывает новую позицию. Если биржа не подтвердила закрытие, бот остаётся в `PYRAMIDING` и повторяет его.

## Что система делает / не делает

✅ Риск-менеджмент через среднюю цену позиции, trend-pyramiding, DCA, straddle, стадийный SL (безубыток/от средней/trailing), TP, автовход по сигналу MRC/Supertrend, бумажный режим, подтверждение ордеров по бирже, сторож позиций без бота, алерты и бэкапы в Telegram, multi-account, Cryptorg и Bybit
❌ Автотрейдинг по сигналам скринера (`services/signals` — информационные), усреднение убытка (мартингейл) в pyramiding-ботах, HFT/арбитраж. Пользователей может быть несколько: данные изолированы, регистрация по одобрению, у каждого свой Telegram и лимит ботов; бэкапы и MCP — у владельца (что осталось — `TODO/1`)

## Troubleshooting

**Backend не запускается** — `docker compose ps`, `docker compose logs backend` (проверить Postgres/Redis healthy). Состояние сервисов также видно на странице `admin/health`.

**Cryptorg-бот не входит** — смотреть `issues` бота в bots-health (или алерт в Telegram) и логи backend `[Cryptorg]`:
- «не удалось прочитать позицию на Bybit» — ключ не работает: на странице `accounts` нажать «Проверить ключ»; в полях должен быть ключ Bybit счёта «Bybit-ликвидность», а не что-то другое;
- «на бирже уже открыта позиция» — на этой монете и стороне есть позиция (ручная или другого бота), вход отменён намеренно;
- «позиция не появилась на бирже за 20 с» — Cryptorg принял команду, но не открыл сделку: проверить бота в Cryptorg (включён ли, хватает ли маржи, выключен ли «непрерывный режим»).

**Алерт «позиция без бота»** — на бирже позиция, которой нет у бота. Проверить счёт: открыта руками, или webhook исполнился, а бот об этом не узнал. Сторож ничего не закрывает сам.

**Бэкап не пришёл** — `docker logs trading_backup`; ручной запуск `docker exec trading_backup python backup.py now`.

**`ErrCode: 10002` / `invalid request, please check your server timestamp`** — часы сервера расходятся с Bybit. Бэкенд это компенсирует сам (`adapters/bybit_clock.py`: поправка по `/v5/market/time` при старте и раз в 10 мин, в логе `[BybitClock]` с величиной расхождения), но синхронизацию времени на VPS всё равно стоит включить: `apt-get install -y chrony && systemctl enable --now chrony`.

**Bybit-бот не открывает позицию** — проверить, что у бота выбран `bybit_account_id`, ключи имеют торговые права для Unified/linear, а флаг `testnet` совпадает с типом ключей; в логах backend искать `[Bybit]`.

**Пирамидинг не срабатывает** — проверить, доходят ли тики цены: в логах backend искать `[TICK]`, `[AVG TRIGGER]`; в логах `price-tracker` — реально ли стримится символ (`GET /subscriptions` на price-tracker); частая причина — сбой HTTP-вызова backend → price-tracker при регистрации стратегии (см. `_notify_price_tracker` в `backend/app/services/websocket.py`).

**Frontend не подключается к API** — проверить `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_SIGNALS_URL`, `NEXT_PUBLIC_BACKTESTER_URL` в `.env`.

## Технологии

**Backend:** FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 16, Redis 7, pybit, aiohttp
**Frontend:** Next.js 14, TypeScript, Tailwind CSS, TanStack Query, Zustand
**Backtester:** Flask, CCXT, `ta` (индикаторы)
**Инфраструктура:** Docker Compose, nginx, Grafana + Loki + Promtail (логи), GitHub Actions (тесты → GHCR → деплой по SSH), Telegram (алерты, бэкапы)

## Документация по модулям

- [`deploy/README.md`](deploy/README.md) — сервер, nginx, GitHub Secrets
- [`services/backup/README.md`](services/backup/README.md) — бэкапы: настройка и восстановление
- [`services/mcp/README.md`](services/mcp/README.md) — kandle MCP: установка, удалённый режим
- [`TODO/`](TODO/) — планы и исследования: форвард-тест (`7`), MCP (`8`), ревью архитектуры (`9`)
- [`services/backtester/README.md`](services/backtester/README.md) — бэктестер: CLI, конфиги, стратегии
- [`services/backtester/README_PINE_STRATEGY.md`](services/backtester/README_PINE_STRATEGY.md) — standalone TradingView Pine-стратегия
- [`services/backtester/migrations/README.md`](services/backtester/migrations/README.md) — миграции БД бэктестера
