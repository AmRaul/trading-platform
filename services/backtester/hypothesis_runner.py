"""Прогон гипотезы — вариации готовой стратегии против её базы, на обучающем и отложенном периодах.

Движок — исследовательские скрипты (research/): те же сигналы и, у шорта альтов, тот же
PositionCalculator, что ведёт живого бота. Меняются только параметры из белого списка BASES —
произвольный код через MCP не запускается: новая логика входа пишется руками за ноутбуком.

Периоды: обучающий START..SPLIT (2021-01 → 2024-07), отложенный SPLIT..END (2024-07 → 2026-10).
Комиссия taker 0.055% и funding — всегда. База (стратегия без изменений) считается на тех же
данных, поэтому сравнение честное, даже если данные с Bybit, а не с Binance, как в карточках.
"""
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "research"))

DATA = ROOT / "data"
START, SPLIT, END = pd.Timestamp("2021-01-01"), pd.Timestamp("2024-07-01"), pd.Timestamp("2026-10-02")
ALT_COINS = ["SOL", "AVAX", "LINK", "ETH", "XRP"]

# Что можно менять и в каких пределах. Значения по умолчанию — параметры живых ботов.
def _pyramid_params(coins: List[str]) -> Dict:
    return {
        "coins": {"default": coins, "kind": "coins"},
        "order_count": {"default": 4, "min": 1, "max": 8, "kind": "int"},
        "step_percent": {"default": 0.5, "min": 0.2, "max": 5.0},
        "sl_percent": {"default": 2.0, "min": 0.5, "max": 10.0},
        "trailing_u": {"default": 1.0, "min": 0.2, "max": 3.0,
                       "hint": "трейлинг = trailing_u × медианный дневной диапазон монеты"},
        "tp_percent": {"default": 100.0, "min": 1.0, "max": 100.0, "hint": "100 — без тейка"},
        "first_order": {"default": 250.0, "min": 50.0, "max": 1000.0},
        # Кульминация объёма против позиции: 15m-свеча против неё с объёмом ≥ climax_k × среднее за сутки
        "climax_k": {"default": 3.0, "min": 1.5, "max": 10.0,
                     "hint": "порог кульминации: объём свечи / средний объём за 96 свечей"},
        "climax_block_hours": {"default": 0, "min": 0, "max": 48, "kind": "int",
                               "hint": "не входить N часов после кульминации против направления; 0 — выкл"},
        "climax_trail_u": {"default": 0.0, "min": 0.0, "max": 1.0,
                           "hint": "после кульминации против позиции стоп = close ± X×U; 0 — выкл"},
        # Фильтры по BTC: входить только по направлению рынка и в монету сильнее/слабее BTC
        "btc_regime": {"default": 0, "min": 0, "max": 1, "kind": "int",
                       "hint": "1 — вход только когда у BTC тот же режим 4h (вверх для лонга, вниз для шорта)"},
        "min_rel_pct": {"default": -100.0, "min": -100.0, "max": 100.0,
                        "hint": "сила к BTC за 7 дней, п.п.: лонг — монета ≥ BTC + X, шорт — ≤ BTC − X; -100 — выкл"},
    }


BASES: Dict[str, Dict] = {
    "alt_short": {
        "title": "Шорт альтов · пирамидинг · 5 монет",
        "description": "режим 4h вниз (EMA50 < EMA200, close < EMA200) + разворот Supertrend 15m; "
                       "пирамидинг в прибыль, стоп от средней, трейлинг в единицах дневной волатильности монеты",
        "deposit": 5000.0,
        "side": "SHORT",
        "params": _pyramid_params(ALT_COINS),
    },
    "mrc_dca": {
        "title": "MRC DCA · 15m Long (BTC; монеты можно сменить или добавить)",
        "description": "цена во внешней полосе MRC 15m при монете выше своей EMA дневки; страховочные в просадку, "
                       "тейк от средней, стоп от средней после полной сетки",
        "deposit_per_coin": 5700.0,
        "params": {
            "coins": {"default": ["BTC"], "kind": "coins",
                      "hint": "каждая монета — свой бот с депозитом 5700; итог — сумма"},
            "safety_orders": {"default": 4, "min": 1, "max": 8, "kind": "int"},
            "step_percent": {"default": 1.55, "min": 0.3, "max": 5.0},
            "martingale": {"default": 2.0, "min": 1.0, "max": 3.0},
            "tp_percent": {"default": 0.97, "min": 0.2, "max": 5.0},
            "sl_percent": {"default": 20.0, "min": 2.0, "max": 50.0},
            "entry_band": {"default": 2, "min": 1, "max": 3, "kind": "int"},
            "trend_ema_period": {"default": 200, "min": 20, "max": 400, "kind": "int"},
            "first_order": {"default": 280.0, "min": 50.0, "max": 1000.0},
        },
    },
    "trend_long": {
        "title": "Лонг по тренду · пирамидинг · ETH (зеркало шорта альтов)",
        "description": "режим 4h вверх (EMA50 > EMA200, close > EMA200) + разворот Supertrend 15m вверх; "
                       "пирамидинг в прибыль, стоп от средней, трейлинг в единицах дневной волатильности. "
                       "Депозит $1000 на монету — полная позиция 1:1, как у шорта альтов",
        "deposit_per_coin": 1000.0,
        "side": "LONG",
        "params": _pyramid_params(["ETH"]),
    },
}


def deposit_of(base: str, params: Dict) -> float:
    b = BASES[base]
    return b["deposit"] if "deposit" in b else b["deposit_per_coin"] * len(params["coins"])


def bases_public() -> Dict:
    return {k: {"title": b["title"], "description": b["description"],
                "deposit": deposit_of(k, {p: v["default"] for p, v in b["params"].items()}),
                "params": {p: {kk: vv for kk, vv in spec.items()} for p, spec in b["params"].items()},
                "periods": {"train": [str(START.date()), str(SPLIT.date())], "holdout": [str(SPLIT.date()), str(END.date())]}}
            for k, b in BASES.items()}


def resolve(base: str, changes: Dict) -> Dict:
    """Полный набор параметров = база + изменения. ValueError — неизвестная база/параметр или вне пределов."""
    if base not in BASES:
        raise ValueError(f"неизвестная стратегия {base!r}; есть: {', '.join(BASES)}")
    spec = BASES[base]["params"]
    unknown = set(changes) - set(spec)
    if unknown:
        raise ValueError(f"нельзя менять {', '.join(sorted(unknown))}; можно: {', '.join(spec)}")
    params = {k: v["default"] for k, v in spec.items()}
    for k, v in changes.items():
        s = spec[k]
        if s.get("kind") == "coins":
            coins = list(dict.fromkeys(str(c).upper().removesuffix("USDT") for c in (v or [])))
            if not coins or len(coins) > 10 or not all(c.isalnum() and len(c) <= 12 for c in coins):
                raise ValueError("coins: от 1 до 10 тикеров, например [\"ETH\", \"SOL\"]")
            params[k] = coins
            continue
        try:
            v = int(v) if s.get("kind") == "int" else float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{k}: нужно число")
        if not s["min"] <= v <= s["max"]:
            raise ValueError(f"{k}: допустимо {s['min']}…{s['max']}")
        params[k] = v
    return params


def params_key(base: str, params: Dict) -> str:
    return hashlib.sha1(json.dumps([base, params], sort_keys=True).encode()).hexdigest()[:12]


# --- данные -----------------------------------------------------------------------

def csv_path(coin: str) -> Path:
    """Как в исследованиях: Binance, если файл есть (локально), иначе скачанный с Bybit."""
    binance = DATA / f"{coin}USDT_15m_binance_futures.csv"
    return binance if binance.exists() else DATA / f"{coin}USDT_15m_bybit_futures.csv"


def download_bybit_15m(coin: str, start: pd.Timestamp = START - pd.Timedelta(days=60),
                       end: pd.Timestamp = END + pd.Timedelta(days=1), get: Optional[Callable] = None) -> Path:
    """История 15m линейного фьючерса Bybit (публичный API, без ключа) — постранично назад по 1000."""
    import requests

    def http_get(params, tries=5):
        for attempt in range(tries):  # сеть/DNS иногда моргают — 200 страниц подряд без повторов не пройдут
            try:
                return requests.get("https://api.bybit.com/v5/market/kline", params=params, timeout=20).json()
            except requests.RequestException:
                if attempt == tries - 1:
                    raise
                time.sleep(2 * (attempt + 1))

    get = get or http_get
    out: Dict[int, List] = {}
    cursor = int(end.timestamp() * 1000)
    stop = int(start.timestamp() * 1000)
    for _ in range(400):
        body = get({"category": "linear", "symbol": f"{coin}USDT", "interval": "15", "limit": 1000, "end": cursor})
        rows = (body.get("result") or {}).get("list") or []
        if body.get("retCode") not in (0, None) or not rows:
            break
        for r in rows:
            out[int(r[0])] = r
        oldest = min(int(r[0]) for r in rows)
        if oldest <= stop:
            break
        cursor = oldest - 1
        time.sleep(0.05)
    if not out:
        raise RuntimeError(f"Bybit не отдал историю {coin}USDT")
    df = pd.DataFrame([{"timestamp": pd.Timestamp(t, unit="ms"), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                       for t, r in sorted(out.items()) if t >= stop])
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{coin}USDT_15m_bybit_futures.csv"
    df.to_csv(path, index=False)
    return path


def ensure_data(coins: List[str], progress: Callable[[str], None] = lambda s: None) -> Dict[str, str]:
    """Нужные CSV: монеты + BTC (сила к BTC у шорта, сам BTC у MRC). Скачивает недостающие."""
    sources = {}
    for coin in dict.fromkeys([*coins, "BTC"]):
        path = csv_path(coin)
        if not path.exists():
            progress(f"скачиваю историю {coin}USDT 15m с Bybit")
            path = download_bybit_15m(coin)
        sources[coin] = "binance" if "binance" in path.name else "bybit"
    return sources


# --- статистика ---------------------------------------------------------------------

def period_stats(equity: pd.Series, deposit: float, trades: pd.DataFrame, a: pd.Timestamp, b: pd.Timestamp,
                 order_count: Optional[int] = None) -> Dict:
    eq = equity[(equity.index >= a) & (equity.index < b)]
    if len(eq) < 2:
        return {"trades": 0}
    eq = eq - eq.iloc[0] + deposit
    dd = float((np.maximum.accumulate(eq.values) - eq.values).max() / deposit * 100)
    years = (b - a).days / 365.25
    ann = float((eq.iloc[-1] - eq.iloc[0]) / deposit * 100 / years)
    months = eq.resample("ME").last()
    mret = months.diff().dropna() / deposit * 100
    tr = trades[(trades["exit"] >= a) & (trades["exit"] < b)] if len(trades) else trades
    out = {
        "annual_return_pct": round(ann, 1),
        "max_drawdown_pct": round(dd, 1),
        "ratio": round(ann / max(dd, 0.1), 2),
        "months_positive_pct": round(float((mret > 0).mean() * 100)) if len(mret) else None,
        "worst_month_pct": round(float(mret.min()), 1) if len(mret) else None,
        "trades": int(len(tr)),
        "trades_per_month": round(len(tr) / max(len(mret), 1), 1),
        "win_rate_pct": round(float((tr["pnl"] > 0).mean() * 100), 1) if len(tr) else None,
    }
    if order_count and len(tr):
        out["full_grid_pct"] = round(float((tr["orders"] >= order_count).mean() * 100), 1)
    return out


# --- стратегии --------------------------------------------------------------------------

def climax_mask(df: pd.DataFrame, k: float, side: str = "SHORT") -> np.ndarray:
    """Кульминация против позиции: свеча против неё (для шорта — рост, для лонга — падение),
    объём ≥ k × средний за 96 предыдущих свечей."""
    avg = df["volume"].rolling(96).mean().shift(1)
    against = (df["close"] > df["open"]) if side == "SHORT" else (df["close"] < df["open"])
    return (against & (df["volume"] >= k * avg)).fillna(False).to_numpy()


def alt_coin_trades(coin: str, p: Dict, coin_cfg: Callable, side: str = "SHORT") -> List:
    """Сделки пирамиды по монете — как short_portfolio.coin_trades (там только шорт), плюс фильтры
    кульминации. Лонг — зеркально: режим 4h вверх и разворот Supertrend вверх.
    При выключенных climax_* — ровно тот же расчёт (сделки базы не меняются)."""
    import short_portfolio as sp
    import trend_pullback_pyramid as tpp

    df = sp.load_15m(coin)
    df = df[(df["timestamp"] >= sp.START) & (df["timestamp"] < sp.END)].reset_index(drop=True)
    k = 0 if side == "LONG" else 1
    sig = tpp.regime(df)[k] & tpp.triggers(df)["st"][k]
    climax = climax_mask(df, p["climax_k"], side) if (p["climax_block_hours"] or p["climax_trail_u"]) else None
    if p["climax_block_hours"]:
        window = int(p["climax_block_hours"] * 4) + 1  # бар кульминации и следующие N часов
        recent = pd.Series(climax).rolling(window, min_periods=1).max().astype(bool).to_numpy()
        sig = sig & ~recent
    btc = sp.load_15m("BTC")
    rel = sp.rel_strength(df, btc)
    if p.get("btc_regime"):
        b = btc[(btc["timestamp"] >= sp.START) & (btc["timestamp"] < sp.END)].reset_index(drop=True)
        b_ok = pd.Series(tpp.regime(b)[k], index=b["timestamp"])
        sig = sig & b_ok.reindex(df["timestamp"], method="ffill").fillna(False).to_numpy(bool)
    if p.get("min_rel_pct", -100.0) > -100.0:
        thr = p["min_rel_pct"] / 100
        ok = rel >= thr if side == "LONG" else rel <= -thr
        sig = sig & np.nan_to_num(ok, nan=False).astype(bool)
    gpos = sp.GRID_IDX.get_indexer(df["timestamp"])
    cfg = coin_cfg(df, "p")
    trail_pct = 0.0
    if p["climax_trail_u"]:
        import donchian_pyramid as dp
        trail_pct = p["climax_trail_u"] * dp.vol_unit(df)
    trades = []
    for i in np.where(sig)[0]:
        t = sp.one_trade(df, i, cfg, side) if not trail_pct \
            else one_trade_climax_trail(df, i, cfg, climax, trail_pct, side)
        if t and gpos[i] >= 0 and gpos[t[0]] >= 0:
            trades.append((int(gpos[i]), int(gpos[t[0]]), t[1], t[2],
                           0.0 if np.isnan(rel[i]) else float(rel[i]), t[3]))
    return trades


def one_trade_climax_trail(df, i, cfg, climax, trail_pct, side="SHORT"):
    """short_portfolio.one_trade + подтяжка стопа после кульминации против позиции:
    по закрытию такой свечи стоп = close × (1 + trail_pct%), если это ближе текущего.
    Дальше обычный трейлинг (стоп только подтягивается)."""
    import donchian_pyramid as dp
    from app.domain.trading.entities import OrderInfo
    from app.domain.trading.position_calculator import PositionCalculator
    from mrc_supertrend_pyramid import FUNDING_15M

    s = 1 if side == "LONG" else -1
    o, h, l, c = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    calc = PositionCalculator(cfg)
    calc.add_order(OrderInfo(1, c[i], cfg["entry_size_usdt"]))
    sl, _ = calc.calculate_stop_loss(side, calc.orders, c[i])
    fees, funding = cfg["entry_size_usdt"] * dp.FEE, 0.0
    floating = [-fees]
    for j in range(i + 1, len(df)):
        funding += s * calc.get_total_size() * FUNDING_15M
        path = [o[j], l[j], h[j], c[j]] if c[j] >= o[j] else [o[j], h[j], l[j], c[j]]
        exit_price = None
        for idx, px in enumerate(path):
            gap = idx == 0
            if calc.is_stop_loss_hit(side, px, sl):
                exit_price = px if gap else sl * (1 - s * dp.SL_SLIPPAGE)
                break
            tp = calc.take_profit_price(side)
            if tp and (px - tp) * s >= 0:
                exit_price = px if gap else tp
                break
            added = False
            while calc.should_add_order(side, px, calc.get_last_order_price()):
                level = calc.get_last_order_price() * (1 + s * (cfg["step_percent"] / 100 - 0.0005))
                fill = px if gap else level
                size = calc.calculate_next_order_size()
                calc.add_order(OrderInfo(len(calc.orders) + 1, fill, size))
                fees += size * dp.FEE
                sl, _ = calc.calculate_stop_loss(side, calc.orders, fill)
                added = True
            if not added:
                new_sl, _ = calc.calculate_stop_loss(side, calc.orders, px)
                if sl == 0 or (new_sl - sl) * s > 0:
                    sl = new_sl
        if exit_price is None and climax[j]:
            tight = c[j] * (1 - s * trail_pct / 100)  # шорт: стоп над ценой, лонг — под ней
            if sl == 0 or (tight - sl) * s > 0:
                sl = tight
        avg, size = calc.calculate_average_price(calc.orders), calc.get_total_size()
        if exit_price is not None:
            fees += size * (exit_price / avg) * dp.FEE
            return j, s * size * (exit_price - avg) / avg - fees - funding, len(calc.orders), np.array(floating)
        floating.append(s * size * (c[j] - avg) / avg - fees - funding)
    return None


def run_pyramid(base: str, p: Dict, progress: Callable[[str], None]) -> Dict:
    import donchian_pyramid as dp
    import mrc_supertrend_pyramid as msp
    import short_portfolio as sp

    msp_load = lambda coin: (pd.read_csv(csv_path(coin), parse_dates=["timestamp"])  # noqa: E731
                             .sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True))
    msp.load_15m = sp.load_15m = msp_load
    import trend_pullback_pyramid as tpp
    tpp.load_15m = msp_load

    deposit = deposit_of(base, p)
    side = BASES[base]["side"]
    dp.DEPOSIT = deposit
    sp.ENTRY = p["first_order"]

    def coin_cfg(df, step):
        cfg = dp.bot_config(0, p["order_count"], False, None)
        cfg.update(entry_size_usdt=p["first_order"], tp_percent=p["tp_percent"], step_percent=p["step_percent"],
                   sl_initial=p["sl_percent"], sl_after_order3=p["sl_percent"],
                   trailing_percent=round(dp.vol_unit(df) * p["trailing_u"], 1))
        return cfg

    by_coin = {}
    for coin in p["coins"]:
        progress(f"считаю {coin}USDT")
        by_coin[coin] = alt_coin_trades(coin, p, coin_cfg, side)
    pnl, taken, _ = sp.portfolio(by_coin, len(p["coins"]), "first")
    equity = pd.Series(deposit + pnl, index=sp.GRID_IDX)
    idx = sp.GRID_IDX
    trades = pd.DataFrame([{"exit": idx[t[1]], "pnl": t[2], "orders": t[3]} for _, t in taken]) \
        if taken else pd.DataFrame(columns=["exit", "pnl", "orders"])
    return {"equity": equity, "trades": trades, "deposit": deposit, "order_count": p["order_count"]}


def run_mrc_dca(p: Dict, progress: Callable[[str], None]) -> Dict:
    import mrc_dca_trend_long as mrc

    mrc.PARAMS.update(safety_orders=p["safety_orders"], step_percent=p["step_percent"], martingale=p["martingale"],
                      tp_percent=p["tp_percent"], sl_percent=p["sl_percent"], first_order=p["first_order"])
    mrc.PARAMS["mrc"] = {**mrc.PARAMS["mrc"], "entry_band": p["entry_band"]}
    mrc.PARAMS["trend_filter"] = {**mrc.PARAMS["trend_filter"], "ema_period": p["trend_ema_period"]}
    pnls, trade_frames = [], []
    for coin in p["coins"]:
        progress(f"считаю {coin}USDT")
        df, signal = mrc.load(csv_path(coin))
        keep = (df["timestamp"] >= START) & (df["timestamp"] < END)
        df, signal = df[keep].reset_index(drop=True), signal[keep.values]
        realized, floating, tr = mrc.simulate(df, signal)
        pnls.append(pd.Series(realized + floating, index=df["timestamp"]))
        if len(tr):
            trade_frames.append(tr.rename(columns={"exit_time": "exit"})[["exit", "pnl", "orders"]])
    deposit = deposit_of("mrc_dca", p)
    idx = pnls[0].index
    for x in pnls[1:]:
        idx = idx.union(x.index)
    total = sum(x.reindex(idx).ffill().fillna(0.0) for x in pnls)
    equity = deposit + total
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames \
        else pd.DataFrame(columns=["exit", "pnl", "orders"])
    return {"equity": equity, "trades": trades, "deposit": deposit, "order_count": p["safety_orders"] + 1}


RUNNERS = {"alt_short": lambda p, pr: run_pyramid("alt_short", p, pr),
           "trend_long": lambda p, pr: run_pyramid("trend_long", p, pr),
           "mrc_dca": run_mrc_dca}


def evaluate(base: str, params: Dict, progress: Callable[[str], None] = lambda s: None) -> Dict:
    r = RUNNERS[base](params, progress)
    eq, tr, dep, oc = r["equity"], r["trades"], r["deposit"], r["order_count"]
    year_end = eq.resample("YE").last()
    prev = year_end.shift(1).fillna(dep)
    return {
        "train": period_stats(eq, dep, tr, START, SPLIT, oc),
        "holdout": period_stats(eq, dep, tr, SPLIT, END, oc),
        # по годам — только для года, целиком лежащего в обучающем периоде (отложенный не подсматриваем)
        "yearly_train_pct": {str(t.year): round(float(v - p) / dep * 100, 1)
                             for t, v, p in zip(year_end.index, year_end.values, prev.values)
                             if t < SPLIT},
    }


def run_hypothesis(base: str, changes: Dict, cache_dir: Path, progress: Callable[[str], None] = lambda s: None) -> Dict:
    """Вариант и база на тех же данных. База кэшируется по (параметры, источник данных)."""
    params = resolve(base, changes)
    base_params = resolve(base, {})
    def coins_of(pp):
        return list(pp.get("coins") or [])
    sources = ensure_data(sorted(set(coins_of(params)) | set(coins_of(base_params))), progress)
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_tag = hashlib.sha1(json.dumps(sources, sort_keys=True).encode()).hexdigest()[:8]
    base_file = cache_dir / f"baseline_{base}_{params_key(base, base_params)}_{data_tag}.json"
    if base_file.exists():
        baseline = json.loads(base_file.read_text())
    else:
        progress("считаю базу (стратегия без изменений)")
        baseline = evaluate(base, base_params, progress)
        base_file.write_text(json.dumps(baseline))
    variant = baseline if params == base_params else evaluate(base, params, progress)
    return {"base": base, "params": params, "base_params": base_params, "data_sources": sources,
            "variant": variant, "baseline": baseline}
