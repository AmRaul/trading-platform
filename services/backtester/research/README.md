# Исследования стратегий

Скрипты, из которых получены карточки готовых стратегий (`backend/app/domain/ready_strategies/data/`),
ожидания форвард-теста (`TODO/7`) и записи журнала kandle. Сопровождение позиции во всех — живой
`PositionCalculator` из `backend`, поэтому бэктест и бот считают одинаково.

## Запуск

Нужны pandas/numpy и код бэкенда в `PYTHONPATH`. Проще всего — в образе backtester-web:

```bash
docker run --rm -v "$PWD":/w:ro -v /tmp/out:/out -w /w/services/backtester \
  -e PYTHONPATH=/w/backend:/w/services/backtester:/w/services/backtester/research \
  --entrypoint python dashboardtrendstrategy-backtester-web:latest \
  research/alt_short_pyramid_card.py --first-order 250 --tp 6 --out /out/card.json
```

Данные — `services/backtester/data/*_15m_binance_futures.csv` (в git не хранятся).
Выходные файлы пишите вне репозитория (`--out`).

## Что где

| Скрипт | Что считает |
|---|---|
| `alt_short_pyramid_card.py` | карточка «Шорт альтов · пирамидинг» (`--tp` — тейк после полной сетки) |
| `alt_short_grid_exits.py` | варианты выхода после 4-го ордера (тейк, безубыток, фиксация, узкий трейлинг) |
| `combo_portfolio.py` | портфель MRC + шорт альтов — ожидания форвард-теста |
| `mrc_dca_trend_long.py` | карточка «MRC DCA · BTC 15m Long» |
| `short_portfolio.py` | портфель шортов: сигнал, сделки по монетам, статистика |
| `trend_pullback_pyramid.py` | режим 4h + триггеры 15m (откат / Supertrend) |
| `donchian_pyramid.py` | общие утилиты: загрузка данных, `vol_unit`, `SPLIT` (07.2024), симуляция |
| `verify_supertrend_live.py` | сверка Supertrend бэктеста с живым расчётом |
| остальные | ранние гипотезы (Donchian, MRC + Supertrend, straddle) |

Обучающий период — до `SPLIT = 2024-07-01`, отложенный — после.
