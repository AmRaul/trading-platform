# kandle-mcp

MCP-сервер kandle для Claude Desktop и Claude Code. Запускается локально (stdio)
и ходит в REST API kandle с вашим логином — так же, как фронтенд. Базу и биржу
напрямую не трогает, торговых действий нет: только чтение и запись в журнал разборов.

## Что умеет

| Инструмент | Что даёт |
|---|---|
| `bots_health` | живы ли боты: сигналы проверяются, цены идут, никто не выпал из цикла |
| `list_bots` | боты с настройками и открытой позицией (фильтр `exchange=paper`) |
| `get_trades` | закрытые сделки за период |
| `portfolio_summary` | итоги по стратегиям: PnL, комиссии, win rate, полные сетки, просадка |
| `get_market_context` | свечи + EMA 20/50/200, RSI, ATR, Bollinger, режим, funding/OI |
| `get_position_context` | позиция бота + контекст + расстояния до стопа/добора/тейка в ATR |
| `log_review`, `list_reviews` | журнал разборов (вердикты второго мнения с исходом сделки) |

Готовые сценарии (prompts): `health_check`, `monthly_review`, `second_opinion`.

## Установка

```bash
cd services/mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q          # 6 тестов, без сети
```

## Подключение

### Claude Code

```bash
claude mcp add kandle --scope user \
  -e KANDLE_URL=https://kandle.tech \
  -e KANDLE_USERNAME=<логин> \
  -e KANDLE_PASSWORD=<пароль> \
  -- "$(pwd)/.venv/bin/python" "$(pwd)/kandle_mcp.py"
```

Проверка: `claude mcp list` → `kandle: ✓ Connected`.

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kandle": {
      "command": "/полный/путь/services/mcp/.venv/bin/python",
      "args": ["/полный/путь/services/mcp/kandle_mcp.py"],
      "env": {
        "KANDLE_URL": "https://kandle.tech",
        "KANDLE_USERNAME": "<логин>",
        "KANDLE_PASSWORD": "<пароль>"
      }
    }
  }
}
```

После правки — перезапустить Claude Desktop.

Пароль хранится в локальном конфиге Claude на этом компьютере и уходит только на `KANDLE_URL`.

## Примеры

- «Проверь, живы ли боты» → `bots_health`
- «Как бумажный портфель с 18.11?» → prompt `monthly_review`
- «Что на дневке по BTC?» → `get_market_context("BTCUSDT", "1d")`
- «Глянь мою позицию бота 12 на 4h» → `get_position_context(12, "4h")`

Бумажные боты — форвард-тест до 2027-02-18: по ним сервер даёт только информацию,
без советов вмешаться (правило в инструкциях сервера).

## Нужно на сервере

Эндпоинты `/api/analytics/*` и таблица `reviews` (миграция `e6f7a8b9c0d1`) —
появляются после деплоя бэкенда из этой же ветки.
