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
   (ожидания и критерии остановки — forward_test_sets, комплект бота — поле forward_test).
   По ним НИКОГДА не советуй
   вмешиваться: закрыть, сдвинуть стоп, отключить. Отвечай только на «действует ли бот
   по своим правилам» и «в пределах ли ожиданий». Индикаторы показывать можно.
2. Никогда не предлагай расширять стоп.
3. Индикаторы, режим рынка, ATR, funding/OI бери из get_market_context /
   get_position_context — не пересчитывай из свечей сам. Результат на стопе/тейке, когда
   трейлинг двинет стоп, следующий ордер — из position_levels в get_position_context.
4a. «Что нового / что изменилось» — what_changed (без since — с прошлой проверки).
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
            if r.status_code == 401 and attempt == 1:  # access-токен живёт 30 мин — перелогин
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
        "forward_test": b.get("forward_test"),
    }
    pos = b.get("open_position")
    if pos:
        brief["open_position"] = {k: pos.get(k) for k in (
            "id", "average_price", "current_sl", "total_size", "order_count", "unrealized_pnl", "last_order_price", "opened_at")}
    return brief


def _strategy_group(b: Dict) -> str:
    """Группа бота для итогов. У бота форвард-теста — его комплект (поле forward_test,
    переименование не ломает); у остальных — название без монеты:
    «Шорт альтов · … · Консервативный · SOLUSDT» → боты одной стратегии вместе."""
    if b.get("forward_test"):
        return f"forward_test:{b['forward_test']}"
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
    """Живы ли боты: по каждому — состояние; у ждущих сигнала (SIGNAL) — когда
    планировщик последний раз проверял сигнал; у ботов в позиции — подписан ли
    на поток цен и когда пришёл последний тик (last_price_tick_sec_ago, >5 мин —
    проблема); не выпал ли из цикла в IDLE. status=problem и issues — что не так."""
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
        # Посчитано логикой самого бота: результат на стопе/тейке с комиссией, с какой цены
        # трейлинг двинет стоп, следующий ордер и стоп после него
        try:
            out["position_levels"] = await api.get(f"/api/analytics/position-levels/{bot_id}")
        except Exception as e:  # без уровней контекст всё равно полезен
            out["position_levels"] = {"error": str(e)[:200]}
    return out


@mcp.tool(annotations=READ)
async def what_changed(since: Optional[str] = None, remember: bool = True) -> Dict:
    """Что изменилось с прошлой проверки: входы, доборы, закрытые сделки (с PnL),
    новые и удалённые боты, смена состояния, сдвиги стопов, изменение плавающего PnL.
    Без since — с прошлого вызова what_changed (сравнение со снимком, который он сохранил).
    since — ISO-дата UTC, сравнение со снимком не позже неё.
    remember=False — посмотреть, не сдвигая точку «прошлой проверки»."""
    return await api.get("/api/analytics/changes", since=since, save=str(remember).lower())


@mcp.tool(annotations=READ)
async def forward_test_sets() -> Dict:
    """Комплекты бумажного форвард-теста: ожидания (бэктест, записаны до старта),
    критерии остановки, что НЕ повод вмешиваться, итог и боты каждой части.
    portfolio — основной (цифры и критерии теста только по нему), take6 — параллельный.
    Группы portfolio_summary «forward_test:<комплект>/<часть>» — это они."""
    return await api.get("/api/analytics/forward-test")


def _iso(ms: Optional[int]) -> Optional[str]:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ms else None


@mcp.tool(annotations=READ)
async def reconcile_position(position_id: int) -> Dict:
    """Сверка позиции (открытой или закрытой) с бэктестом на тех же свечах Bybit:
    был ли сигнал на свече входа, те же ли доборы, тот же ли выход.
    verdict: match — совпало; price_drift — механика та же, цены/время дальше допуска
    (0.15% / 5 мин); mismatch — другой вход, другое число ордеров или другой выход
    (критерий остановки 4 форвард-теста); manual — закрыта руками.
    position_id — из get_trades (поле position_id) или list_bots (open_position.id)."""
    r = await api.get(f"/api/analytics/reconcile/{position_id}")
    for row in r.get("orders", []):
        for k in ("live_time_ms", "replay_time_ms"):
            row[k.replace("_ms", "")] = _iso(row.pop(k, None))
    sig = r.get("entry_signal")
    if sig:
        sig["signal_candle_close"] = _iso(sig.pop("signal_candle_close_ms", None))
    return r


@mcp.tool(annotations=READ)
async def reconcile_trades(since: Optional[str] = None, until: Optional[str] = None,
                           exchange: Optional[str] = "paper") -> Dict:
    """Сверка с бэктестом ВСЕХ закрытых сделок за период одной сводкой (вместо reconcile_position
    по одной): verdicts — сколько match / price_drift / mismatch / manual; средний и максимальный
    разрыв цены ордеров и выхода, %; not_match — сделки не-match с причинами.
    mismatch — критерий остановки 4 форвард-теста. since/until — ISO-дата UTC.
    По умолчанию — бумажные боты; exchange=None — все."""
    r = await api.get("/api/analytics/reconcile-batch", since=since, until=until, exchange=exchange)
    r.pop("candle_fetches", None)
    return r


@mcp.tool(annotations=READ)
async def account_overview(account_id: Optional[int] = None, days: int = 30) -> Dict:
    """Счёт Cryptorg глазами биржи (ключ Bybit «только чтение»): все открытые позиции
    и закрытые сделки за days дней, включая ручные и других ботов Cryptorg; у каждой —
    какой бот её ведёт/вёл (bot=None — не наш бот). PnL закрытых — как считает Bybit.
    Без account_id — по всем аккаунтам Cryptorg с ключом. Только чтение."""
    accounts = await api.get("/api/accounts/")
    if account_id is not None:
        accounts = [a for a in accounts if a["id"] == account_id]
        if not accounts:
            raise ToolError(f"Аккаунт {account_id} не найден")
    out = {}
    for a in accounts:
        if not (a.get("has_api_key") and a.get("has_api_secret")):
            out[a["name"]] = {"ok": False, "error": "ключ Bybit не задан — счёт не виден"}
            continue
        data = await api.get(f"/api/accounts/{a['id']}/exchange", days=days)
        for p in data.get("positions", []):
            p["opened_at"] = _iso(p.pop("opened_at_ms", None))
        for c in data.get("closed", []):
            c["closed_at"] = _iso(c.pop("closed_at_ms", None))
        out[a["name"]] = data
    return {"accounts": out}


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
1. Вызови bots_health (у ботов в позиции важен свежий тик цены, у ждущих сигнала — свежая проверка).
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

Ожидания, критерии остановки, «что не повод вмешиваться» и итог — из forward_test_sets()
(записаны до старта 18.11.2026, не меняются). Комплект бота — поле forward_test, не название.
- portfolio — основной портфель ($10 700): части mrc (MRC DCA BTC, $5 700) и short (шорт-пирамида 5 альтов, $5 000).
  Цифры форвард-теста и критерии остановки считаются ТОЛЬКО по нему.
- take6 — параллельный комплект (тот же шорт + тейк 6% от средней после 4-го ордера, $5 000), в цифры
  портфеля и критерии не входит. Сравнивай с portfolio/short ЗА ТОТ ЖЕ период (с первой сделки комплекта):
  разница в PnL, просадке, доле выходов по тейку (exit_reason TP_HIT).
- боты без forward_test (ручные, напр. HYPEUSDT) — одной строкой, вне форвард-теста.

Шаги:
1. forward_test_sets() — ожидания и состав комплектов; bots_health — все ли боты комплектов живы.
2. portfolio_summary(since="{since}"{f', until="{until}"' if until else ''}, exchange="paper") — группы
   «forward_test:portfolio/mrc», «forward_test:portfolio/short», «forward_test:take6/short».
3. get_market_context("BTCUSDT", "1d") — режим BTC (объясняет активность MRC).
3a. Сверка с бэктестом (критерий 4): reconcile_trades(since="{since}"{f', until="{until}"' if until else ''})
   — все закрытые сделки периода одной сводкой. mismatch по любой — назови его первым: это критерий
   остановки, результат до починки не считается (детали — reconcile_position по position_id из not_match).
   price_drift — приведи средний разрыв цены; это проскальзывание, не поломка.
4. Сравни основной портфель с ожиданиями: доходность в % от депозитов, просадка, число сделок, доля
   полных сеток у шорта. Затем — take6 против своих ожиданий и против portfolio/short.
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
