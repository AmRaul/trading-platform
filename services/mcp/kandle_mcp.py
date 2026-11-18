"""
kandle-mcp — MCP-сервер kandle для Claude.
  stdio (по умолчанию)  — Claude Code / Claude Desktop на своём компьютере;
  http                  — удалённый коннектор для claude.ai и мобильного приложения.

Клиент REST API kandle с правами пользователя: ходит туда же, куда фронтенд,
базу и биржу напрямую не трогает. Торговых действий нет — только чтение
и запись в журнал разборов.

Переменные окружения:
    KANDLE_URL            — https://kandle.tech (по умолчанию) или http://backend:8000
    KANDLE_USERNAME       — логин kandle
    KANDLE_PASSWORD       — пароль kandle
    KANDLE_MCP_TRANSPORT  — stdio | http
    KANDLE_MCP_TOKEN      — только для http: секрет в пути, сервер отвечает лишь на
                            /mcp/<token> (claude.ai-коннектор с этим URL и есть авторизация)
    KANDLE_MCP_PORT       — только для http, по умолчанию 8030
"""
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

FORWARD_TEST_END = "2027-02-18"

INSTRUCTIONS = f"""
kandle — платформа торговых ботов пользователя (пирамидинг, DCA, straddle) на Bybit/Cryptorg
и в бумажном режиме (exchange=paper: живые цены Bybit, без реальных ордеров, комиссия 0.055%
за исполнение уже вычтена из PnL сделки).

Правила:
1. Бумажные боты (exchange=paper) — форвард-тест портфеля до {FORWARD_TEST_END}
   (ожидания и критерии остановки — в prompt monthly_review). По ним НИКОГДА не советуй
   вмешиваться: закрыть, сдвинуть стоп, отключить. Отвечай только на «действует ли бот
   по своим правилам» и «в пределах ли ожиданий». Индикаторы показывать можно.
2. Никогда не предлагай расширять стоп.
3. Индикаторы, режим рынка, ATR, funding/OI бери из get_market_context /
   get_position_context — не пересчитывай из свечей сам.
4. Разборы (monthly_review, health_check, second_opinion) записывай через log_review.
   У second_opinion вердикт обязан быть проверяемым: action, first_hit, confidence, key_risk.
5. Суммы — USDT. Время — UTC.
""".strip()

mcp = MCPServer("kandle", instructions=INSTRUCTIONS)
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


class KandleAPI:
    def __init__(self):
        self.base = os.environ.get("KANDLE_URL", "https://kandle.tech").rstrip("/")
        self.username = os.environ.get("KANDLE_USERNAME")
        self.password = os.environ.get("KANDLE_PASSWORD")
        self.token: Optional[str] = None
        self.http = httpx.AsyncClient(base_url=self.base, timeout=30.0)

    async def _login(self):
        if not self.username or not self.password:
            raise ToolError("Задайте KANDLE_USERNAME и KANDLE_PASSWORD в конфиге MCP-сервера")
        try:
            r = await self.http.post("/api/auth/login", json={"username": self.username, "password": self.password})
        except httpx.HTTPError as e:
            raise ToolError(f"kandle недоступен ({self.base}): {e}")
        if r.status_code != 200:
            raise ToolError(f"Логин в kandle не удался: {r.status_code} {r.text[:200]}")
        self.token = r.json()["access_token"]

    async def request(self, method: str, path: str, **kw) -> Any:
        if not self.token:
            await self._login()
        for attempt in (1, 2):
            try:
                r = await self.http.request(method, path, headers={"Authorization": f"Bearer {self.token}"}, **kw)
            except httpx.HTTPError as e:
                raise ToolError(f"kandle недоступен ({self.base}): {e}")
            if r.status_code == 401 and attempt == 1:  # токен истёк (7 дней) — перелогин
                await self._login()
                continue
            if r.status_code >= 400:
                raise ToolError(f"{method} {path}: {r.status_code} {r.text[:300]}")
            return r.json()

    async def get(self, path: str, **params) -> Any:
        return await self.request("GET", path, params={k: v for k, v in params.items() if v is not None})


api = KandleAPI()


# ── helpers ──────────────────────────────────────────────────────────────────

def _bot_brief(b: Dict) -> Dict:
    cfg = b.get("config") or {}
    brief = {
        "bot_id": b["id"], "name": b["name"], "symbol": b["symbol"], "side": b["side"],
        "exchange": b.get("exchange"), "state": b["state"], "type": cfg.get("bot_type", "pyramiding"),
        "total_pnl": round(b.get("total_pnl") or 0.0, 2),
        "config": {k: cfg.get(k) for k in (
            "entry_size_usdt", "order_count", "step_percent", "pyramiding_multiplier", "dca_multiplier",
            "sl_initial", "sl_after_order3", "use_trailing", "trailing_percent", "tp_percent", "leverage", "cycle",
        ) if cfg.get(k) is not None},
        "entry_signal": cfg.get("entry_signal"),
    }
    pos = b.get("open_position")
    if pos:
        brief["open_position"] = {k: pos.get(k) for k in (
            "id", "average_price", "current_sl", "total_size", "order_count", "unrealized_pnl", "last_order_price", "opened_at")}
    return brief


def _strategy_group(b: Dict) -> str:
    """«Шорт альтов · … · Консервативный · SOLUSDT» → без монеты: боты одной стратегии вместе."""
    name, sym = b["name"], b["symbol"]
    return name[: -len(sym) - 3] if name.endswith(f" · {sym}") else name


def _stats(trades: List[Dict], order_count: Dict[int, int]) -> Dict:
    pnl = [t["pnl"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnl:  # просадка по закрытым сделкам (плавающий PnL открытых — отдельно)
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    full = sum(1 for t in trades if order_count.get(t["bot_id"]) and t["total_orders"] >= order_count[t["bot_id"]])
    return {
        "trades": len(trades),
        "pnl": round(sum(pnl), 2),
        "fees": round(sum(t.get("fees") or 0.0 for t in trades), 2),
        "win_rate_pct": round(len(wins) / len(pnl) * 100, 1) if pnl else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "max_drawdown_closed": round(max_dd, 2),
        "full_grid_trades": full,
        "exit_reasons": dict(sorted(_count(t["exit_reason"] for t in trades).items())),
    }


def _count(items) -> Dict[str, int]:
    c: Dict[str, int] = defaultdict(int)
    for i in items:
        c[i] += 1
    return c


def _dist(price: float, level: Optional[float], atr: Optional[float]) -> Optional[Dict]:
    if not level:
        return None
    return {"price": level, "pct": round((level / price - 1) * 100, 2),
            "atr": round((level - price) / atr, 2) if atr else None}


# ── tools ────────────────────────────────────────────────────────────────────

@mcp.tool(annotations=READ)
async def bots_health() -> Dict:
    """Живы ли боты: по каждому — состояние, проверяет ли планировщик сигнал
    (SIGNAL), подписан ли на поток цен (позиция открыта), не выпал ли из цикла
    в IDLE. status=problem и issues — что не так."""
    data = await api.get("/api/analytics/bots-health")
    for b in data["bots"]:
        if b.get("last_signal_check"):
            b["last_signal_check"].pop("checked_at_ms", None)
    return data


@mcp.tool(annotations=READ)
async def list_bots(exchange: Optional[str] = None) -> List[Dict]:
    """Боты пользователя с ключевыми настройками и открытой позицией (живой PnL).
    exchange: paper | bybit | cryptorg — фильтр по площадке."""
    bots = await api.get("/api/bots/")
    return [_bot_brief(b) for b in bots if not exchange or b.get("exchange") == exchange]


@mcp.tool(annotations=READ)
async def get_trades(since: Optional[str] = None, until: Optional[str] = None,
                     bot_id: Optional[int] = None) -> List[Dict]:
    """Закрытые сделки за период (since/until — ISO-дата, UTC), от старых к новым.
    pnl уже за вычетом fees, если fees не null (paper)."""
    trades = await api.get("/api/analytics/trades", since=since, until=until, bot_id=bot_id)
    keep = ("id", "bot_id", "position_id", "symbol", "side", "entry_price", "average_price", "exit_price",
            "total_size", "total_orders", "exit_reason", "pnl", "pnl_percent", "fees", "opened_at", "closed_at")
    return [{k: t.get(k) for k in keep} for t in trades]


@mcp.tool(annotations=READ)
async def portfolio_summary(since: Optional[str] = None, until: Optional[str] = None,
                            exchange: Optional[str] = "paper") -> Dict:
    """Итоги по стратегиям и ботам за период: сделки, PnL, комиссии, win rate,
    profit factor, просадка по закрытым сделкам, сделки с полной сеткой,
    причины выхода, плюс плавающий PnL открытых позиций.
    По умолчанию — бумажный форвард-тест (exchange=paper); exchange=None — все боты."""
    bots = [b for b in await api.get("/api/bots/") if not exchange or b.get("exchange") == exchange]
    by_id = {b["id"]: b for b in bots}
    trades = [t for t in await api.get("/api/analytics/trades", since=since, until=until) if t["bot_id"] in by_id]
    order_count = {b["id"]: (b.get("config") or {}).get("order_count") for b in bots}

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for t in trades:
        groups[_strategy_group(by_id[t["bot_id"]])].append(t)
    strategies = {}
    for name in sorted({_strategy_group(b) for b in bots}):
        g_bots = [b for b in bots if _strategy_group(b) == name]
        strategies[name] = {
            **_stats(groups.get(name, []), order_count),
            "unrealized_pnl": round(sum((b.get("open_position") or {}).get("unrealized_pnl") or 0.0 for b in g_bots), 2),
            "bots": [{"bot_id": b["id"], "symbol": b["symbol"], "state": b["state"],
                      **{k: v for k, v in _stats([t for t in trades if t["bot_id"] == b["id"]], order_count).items()
                         if k in ("trades", "pnl", "fees", "full_grid_trades")}} for b in g_bots],
        }
    return {
        "period": {"since": since, "until": until},
        "exchange": exchange,
        "total": {**_stats(trades, order_count),
                  "unrealized_pnl": round(sum((b.get("open_position") or {}).get("unrealized_pnl") or 0.0 for b in bots), 2)},
        "strategies": strategies,
        "note": "max_drawdown_closed — по закрытым сделкам в USDT; плавающий минус открытых позиций — в unrealized_pnl",
    }


@mcp.tool(annotations=READ)
async def get_market_context(symbol: str, timeframe: str = "1d", bars: int = 30) -> Dict:
    """Пакет для разбора монеты: последние bars свечей (сжато) и посчитанные kandle
    индикаторы — EMA 20/50/200 (расстояние в % и ATR), RSI14, ATR14, Bollinger 20,
    режим (up/down/mixed как у стратегий), экстремумы окна, объём, funding и OI Bybit.
    timeframe: 15m | 1h | 4h | 1d | 1w. Последняя свеча — текущая, не закрыта."""
    return await api.get("/api/analytics/market-context", symbol=symbol.upper(), timeframe=timeframe, bars=bars)


@mcp.tool(annotations=READ)
async def get_position_context(bot_id: int, timeframe: str = "1d", bars: int = 30) -> Dict:
    """Позиция бота + рыночный контекст по её монете + расстояния от текущей цены
    до средней, стопа, следующего добора и тейка (в % и в ATR выбранного ТФ)."""
    bots = await api.get("/api/bots/")
    bot = next((b for b in bots if b["id"] == bot_id), None)
    if not bot:
        raise ToolError(f"Бот {bot_id} не найден")
    brief = _bot_brief(bot)
    ctx = await get_market_context(bot["symbol"], timeframe, bars)
    out: Dict[str, Any] = {"bot": brief, "market": ctx}
    if bot.get("exchange") == "paper":
        out["forward_test"] = (f"Бумажный бот форвард-теста до {FORWARD_TEST_END}: только информация, "
                               "без советов вмешаться.")
    pos = brief.get("open_position")
    if pos and ctx.get("price"):
        price, atr, cfg = ctx["price"], ctx.get("atr14"), brief["config"]
        sign = 1 if bot["side"] == "LONG" else -1
        levels = {"average": _dist(price, pos.get("average_price"), atr),
                  "stop": _dist(price, pos.get("current_sl"), atr)}
        if pos.get("last_order_price") and cfg.get("step_percent") and pos["order_count"] < (cfg.get("order_count") or 0):
            # пирамидинг доливает по ходу движения, DCA — против
            k = -sign if brief["type"] == "dca" else sign
            levels["next_order"] = _dist(price, pos["last_order_price"] * (1 + k * cfg["step_percent"] / 100), atr)
        tp = cfg.get("tp_percent")
        if tp and tp < 100 and pos.get("average_price"):
            levels["take_profit"] = _dist(price, pos["average_price"] * (1 + sign * tp / 100), atr)
        out["levels_from_price"] = levels
        out["timeframe_atr"] = atr
    return out


@mcp.tool()
async def log_review(kind: str, summary: str, bot_id: Optional[int] = None, position_id: Optional[int] = None,
                     symbol: Optional[str] = None, verdict: Optional[Dict[str, Any]] = None) -> Dict:
    """Записать разбор в журнал kandle.
    kind: monthly_review | health_check | second_opinion | note.
    second_opinion: укажи position_id и verdict = {action: hold|reduce|close,
    first_hit: stop|target, confidence: 0..1, key_risk: str} — по закрытию
    позиции list_reviews покажет исход и можно проверить, сбылся ли вердикт."""
    if kind == "second_opinion":
        missing = [k for k in ("action", "first_hit", "confidence", "key_risk") if k not in (verdict or {})]
        if missing or not position_id:
            raise ToolError(f"second_opinion требует position_id и verdict с полями: {missing or 'ok'}")
    return await api.request("POST", "/api/analytics/reviews", json={
        "kind": kind, "summary": summary, "bot_id": bot_id, "position_id": position_id,
        "symbol": symbol.upper() if symbol else None, "verdict": verdict})


@mcp.tool(annotations=READ)
async def list_reviews(kind: Optional[str] = None, bot_id: Optional[int] = None, limit: int = 20) -> List[Dict]:
    """Журнал разборов от новых к старым. У second_opinion по закрытым позициям
    есть outcome (как закрылась сделка) — для проверки точности вердиктов."""
    return await api.get("/api/analytics/reviews", kind=kind, bot_id=bot_id, limit=limit)


# ── prompts ──────────────────────────────────────────────────────────────────

@mcp.prompt()
def health_check() -> str:
    """Проверить, что боты живы (не затёрлись, сигналы проверяются, цены идут)."""
    return """Проверь, живы ли мои боты.
1. Вызови bots_health.
2. Если problems = 0 — коротко: сколько ботов, в каких состояниях, когда последний раз проверялся сигнал.
3. Если есть проблемы — по каждой: бот, что не так, вероятная причина, что сделать (например,
   перезапустить ожидание сигнала). Ничего не меняй сам — у тебя нет торговых инструментов.
4. Запиши итог через log_review(kind="health_check").
Это не разбор результатов: про PnL не рассуждай."""


@mcp.prompt()
def monthly_review(since: str, until: Optional[str] = None) -> str:
    """Ежемесячный разбор бумажного форвард-теста против ожиданий (TODO/7-paper-forward-test.md)."""
    period = f"с {since}" + (f" по {until}" if until else " по сегодня")
    return f"""Ежемесячный разбор бумажного форвард-теста {period}.

Ожидания (бэктест 2021–2026, записаны до старта 18.11.2026, не меняются):
- Портфель $10 700 = MRC DCA BTC ($5 700) + шорт-пирамида 5 альтов ($5 000).
- Портфель: ~15.8%/год, медиана месяца +0.5% (~$54), 5-й перцентиль месяца −2.6%, худший месяц −7.4%,
  за 3 месяца норма от −4% до +15%, худшие 3 месяца в истории −10%. Макс. просадка 14.4%.
- MRC: ~4 сделки/мес, но при BTC ниже EMA200 1d не торгует — ноль сделок нормален.
- Шорт альтов: ~39 сделок/мес, 44% месяцев в плюсе, прибыль только от сделок с полной сеткой (4 ордера),
  сделки с 1–2 ордерами — убыточны и это норма.
Критерии остановки: просадка портфеля > 20% ($2 140); любые 3 месяца хуже −10%; просадка шорт-части > 35%
($1 750) или MRC-части > 25% ($1 425); расхождение входов/выходов с бэктестом.

Шаги:
1. bots_health — все ли 6 бумажных ботов живы.
2. portfolio_summary(since="{since}"{f', until="{until}"' if until else ''}, exchange="paper").
3. get_market_context("BTCUSDT", "1d") — режим BTC (объясняет активность MRC).
4. Сравни с ожиданиями: доходность в % от депозитов, просадка, число сделок, доля полных сеток у шорта.
   Отдельно: сработал ли какой-то критерий остановки.
5. Вывод одной строкой: «в пределах ожиданий» / «хуже ожиданий, но в норме» / «критерий остановки».
   Никаких советов менять параметры — до 2027-02-18 они заморожены.
6. log_review(kind="monthly_review", summary=<итог с цифрами>)."""


@mcp.prompt()
def second_opinion(bot_id: int, my_thesis: str, would_act_if: str, timeframe: str = "1d") -> str:
    """Второе мнение по позиции: сильнейший аргумент против и проверяемый вердикт в журнал."""
    return f"""Второе мнение по позиции бота {bot_id}.
Мой тезис: {my_thesis}
Я изменю действие, если: {would_act_if}

1. get_position_context(bot_id={bot_id}, timeframe="{timeframe}"); если нужно — ещё 4h.
   Если бот бумажный (forward_test в ответе) — дай только картину индикаторов и
   проверку условия, без вердикта и без советов вмешаться, в журнал не пиши.
2. Найди, что я мог не увидеть: режим против позиции, уровни между ценой и целью,
   расстояние до стопа в ATR (стоп ближе 1 ATR — шум может выбить), funding/OI, объём.
3. Сильнейший аргумент ПРОТИВ моей позиции.
4. Выполняется ли моё условие действия — да/нет и почему.
5. Никогда не предлагай расширять стоп.
6. log_review(kind="second_opinion", bot_id={bot_id}, position_id=<id позиции>, summary=...,
   verdict={{"action": "hold|reduce|close", "first_hit": "stop|target", "confidence": 0.5-0.9,
   "key_risk": "..."}})."""


MIN_TOKEN_LEN = 32


def http_path(token: Optional[str]) -> str:
    """Путь удалённого MCP: секрет в URL. Короткий/пустой токен — отказ запускаться,
    иначе сервер с данными ботов оказался бы открыт по угадываемому адресу."""
    token = (token or "").strip()
    if len(token) < MIN_TOKEN_LEN or not token.replace("-", "").replace("_", "").isalnum():
        raise SystemExit(f"KANDLE_MCP_TOKEN: нужен случайный токен из [A-Za-z0-9_-], ≥{MIN_TOKEN_LEN} символов "
                         "(например: python -c 'import secrets; print(secrets.token_urlsafe(32))')")
    return f"/mcp/{token}"


def main():
    if os.environ.get("KANDLE_MCP_TRANSPORT", "stdio") == "http":
        mcp.run(
            "streamable-http",
            host="0.0.0.0",  # в контейнере; наружу порт проброшен только на 127.0.0.1, вход — через nginx
            port=int(os.environ.get("KANDLE_MCP_PORT", "8030")),
            streamable_http_path=http_path(os.environ.get("KANDLE_MCP_TOKEN")),
            stateless_http=True,  # переживает рестарт контейнера без «потерянных сессий» у клиента
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
