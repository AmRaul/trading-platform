"""Как шорт альтов ведёт себя на молодых монетах, которые после листинга сильно выросли.
Описательный разбор на уже проверенных листингах 07.2024–06.2025 (young_listings_short.py), без подбора параметров.
Сделки — по каждой монете отдельно, без лимита слотов. Окно — первые 180 дней после первой свечи."""
import json
import numpy as np, pandas as pd
import hypothesis_runner as hr
import short_portfolio as sp
import mrc_supertrend_pyramid as msp, trend_pullback_pyramid as tpp
import young_listings_short as yl

DAYS = 180

if __name__ == "__main__":
    coins = list(json.load(open("young_listings_short_results.json"))["per_coin"])
    load = lambda c: (pd.read_csv(hr.csv_path(c), parse_dates=["timestamp"])  # noqa: E731
                      .sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True))
    msp.load_15m = sp.load_15m = tpp.load_15m = load
    p = hr.resolve("alt_short", {})
    sp.ENTRY = p["first_order"]
    rows = []
    for c in coins:
        df = load(c)
        t0 = df.timestamp.iloc[0]
        w = df[df.timestamp < t0 + pd.Timedelta(days=DAYS)]
        close = w.set_index("timestamp")["close"].resample("1h").last().dropna()
        peak_x = float(close.max() / close.iloc[0])
        # сильнейший рост: от минимума к последующему максимуму
        run_up = float((close / close.cummin()).max())
        # часы «в ракете»: цена >= 2× минимума за прошлые 30 дней
        pump = close >= 2 * close.rolling(24 * 30, min_periods=24).min()
        p["coins"] = [c]
        tr = yl.coin_trades(c, p)
        idx = sp.GRID_IDX
        inwin = [t for t in tr if idx[t[0]] < t0 + pd.Timedelta(days=DAYS)]
        pnls = [t[2] for t in inwin]
        in_pump = [t[2] for t in inwin if bool(pump.reindex([idx[t[0]].floor("1h")]).fillna(False).iloc[0])]
        first_trade = str(idx[inwin[0][0]].date()) if inwin else None
        rows.append({"coin": c, "listed": str(t0.date()), "peak_x_from_listing": round(peak_x, 1),
                     "max_run_up_x": round(run_up, 1), "pump_hours_pct": round(float(pump.mean() * 100)),
                     "first_trade": first_trade, "trades_180d": len(pnls), "pnl_180d": round(sum(pnls)),
                     "worst_trade": round(min(pnls)) if pnls else None,
                     "trades_in_pump": len(in_pump), "pnl_in_pump": round(sum(in_pump))})
        print(json.dumps(rows[-1]), flush=True)
    d = pd.DataFrame(rows).sort_values("max_run_up_x", ascending=False)
    print(d.to_string(index=False))
    big = d[d.max_run_up_x >= 3]
    print("\nмонеты с ростом >=3x от минимума:", len(big), "pnl 180д:", int(big.pnl_180d.sum()),
          "| остальные:", len(d) - len(big), "pnl:", int(d[d.max_run_up_x < 3].pnl_180d.sum()))
    print("худшая сделка за всё окно:", int(d.worst_trade.min()), "(стоп 2% от средней; позиция до $1000)")
    d.to_json("young_listings_pumps.json", orient="records", indent=1)
