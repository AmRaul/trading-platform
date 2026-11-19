"""
Сверка позиции бота с бэктестом на тех же свечах (MCP reconcile_position) —
критерий 4 форвард-теста: «paper-бот и бэктест расходятся — другой вход или выход».

1. Вход: был ли сигнал на свече, на закрытии которой бот вошёл (те же 1000 закрытых
   свечей сигнального и трендового ТФ, что видел планировщик).
2. Сопровождение: replay_position на минутках от входа до выхода (или до сейчас) —
   доборы, стоп, тейк, трейлинг той же логикой, что у живого бота.
3. compare_with_replay: вердикт match / price_drift / mismatch / manual.
"""
import time
from typing import Dict, List, Optional

from app.application.signals.check_entry_signal import INTERVAL_MS, SIGNAL_CANDLES, TREND_CANDLES
from app.domain.signals.entry_signal import closed_candles, evaluate_entry
from app.domain.trading.reconcile import compare_with_replay
from app.domain.trading.replay import replay_position
from app.ports.market_data import MarketData

REPLAY_INTERVAL = "1"
REPLAY_INTERVAL_MS = 60_000
ENTRY_DELAY_TOL_MS = 5 * 60_000  # вход по сигналу — через секунды после закрытия свечи


def _ms(dt) -> Optional[int]:
    return int(dt.timestamp() * 1000) if dt else None


class ReconcilePositionUseCase:
    def __init__(self, market_data: MarketData):
        self.market = market_data

    async def check_entry_signal(self, symbol: str, side: str, cfg: Dict, entry_ms: int) -> Dict:
        tf = cfg.get("timeframe", "15")
        interval = INTERVAL_MS[tf]
        signal_close = entry_ms - entry_ms % interval
        raw = await self.market.get_klines(symbol, tf, SIGNAL_CANDLES, end_ms=signal_close - 1)
        signal_candles = closed_candles(raw, interval, signal_close)
        trend_candles = None
        if cfg.get("trend_ema_period"):
            ttf = cfg.get("trend_timeframe", "D")
            raw_trend = await self.market.get_klines(symbol, ttf, TREND_CANDLES, end_ms=signal_close - 1)
            trend_candles = closed_candles(raw_trend, INTERVAL_MS[ttf], signal_close)
        r = evaluate_entry(side, signal_candles, trend_candles, cfg)
        close = signal_candles[-1]["close"] if signal_candles else None
        return {
            "signal_candle_close_ms": signal_close,
            "entry_delay_sec": round((entry_ms - signal_close) / 1000),
            "triggered": bool(r.triggered),
            "reason": r.reason,
            "trend_ok": r.trend_ok,
            "signal_close_price": close,
        }

    async def execute(self, *, bot, position, orders: List, trade=None, now_ms: Optional[int] = None) -> Dict:
        now_ms = now_ms or int(time.time() * 1000)
        cfg = bot.config or {}
        if cfg.get("bot_type") == "straddle":
            return {"position_id": position.id, "bot_id": bot.id, "verdict": "unsupported",
                    "issues": ["сверка стрэддла (две ноги) пока не поддерживается"]}
        filled = sorted([o for o in orders if o.status in (None, "FILLED")], key=lambda o: o.order_number)
        if not filled:
            return {"position_id": position.id, "verdict": "no_data", "issues": ["у позиции нет исполненных ордеров"]}

        live_orders = [{"number": o.order_number, "price": o.price,
                        "time_ms": _ms(o.filled_at) or _ms(o.created_at)} for o in filled]
        entry_ms = live_orders[0]["time_ms"] or _ms(position.opened_at)
        live_exit = None
        if trade is not None:
            live_exit = {"time_ms": _ms(trade.closed_at), "price": trade.exit_price, "reason": trade.exit_reason}
        end_ms = live_exit["time_ms"] if live_exit else now_ms

        notes = ["Сверка по текущему конфигу бота: если его меняли после входа, результат неточен.",
                 "Бэктест идёт по минутным свечам, бот — по тикам: расхождения цены в пределах "
                 "допуска и проскальзывание рыночного ордера — норма."]
        if not position.is_bot_managed:
            notes.append("Позицию взяли под ручное управление — после этого бот её не вёл.")

        result: Dict = {"position_id": position.id, "bot_id": bot.id, "symbol": bot.symbol, "side": bot.side,
                        "exchange": bot.exchange, "status": "closed" if live_exit else "open"}

        issues_extra: List[str] = []
        entry_signal = cfg.get("entry_signal")
        if entry_signal:
            sig = await self.check_entry_signal(bot.symbol, bot.side, entry_signal, entry_ms)
            if sig["signal_close_price"]:
                sig["entry_vs_close_pct"] = round((live_orders[0]["price"] / sig["signal_close_price"] - 1) * 100, 3)
            result["entry_signal"] = sig
            if sig["entry_delay_sec"] * 1000 > ENTRY_DELAY_TOL_MS:
                notes.append(f"Вход через {sig['entry_delay_sec']} с после закрытия свечи — похоже на ручной "
                             "вход, а не по сигналу; проверка сигнала к нему неприменима.")
            elif not sig["triggered"]:
                issues_extra.append(f"вход без сигнала: на свече входа бэктест не видит сигнала ({sig['reason']})")
        else:
            result["entry_signal"] = None
            notes.append("У бота нет сигнала входа (ручной вход) — проверяется только сопровождение.")

        start = entry_ms - entry_ms % REPLAY_INTERVAL_MS
        candles = await self.market.get_klines_range(bot.symbol, REPLAY_INTERVAL, start, end_ms)
        if not candles:
            result.update(verdict="no_data", issues=["не удалось загрузить свечи Bybit"], notes=notes)
            return result
        if candles[-1]["timestamp"] + REPLAY_INTERVAL_MS < end_ms - 2 * REPLAY_INTERVAL_MS:
            notes.append("Свечи загружены не до конца сделки (слишком длинная) — сверен только начальный отрезок.")

        replay = replay_position(cfg, bot.side, live_orders[0]["price"], entry_ms, candles,
                                 interval_ms=REPLAY_INTERVAL_MS, trailing_enabled=position.trailing_enabled)
        cmp = compare_with_replay(live_orders, live_exit, replay)
        if live_exit is None and replay.is_open and position.current_sl and replay.current_sl:
            sl_diff = round((position.current_sl / replay.current_sl - 1) * 100, 3)
            cmp["stop"] = {"live": position.current_sl, "replay": round(replay.current_sl, 8), "diff_pct": sl_diff}
            if abs(sl_diff) > cmp["tolerance"]["price_pct"]:
                cmp["drift"].append(f"текущий стоп: бот {position.current_sl:.6g}, бэктест "
                                    f"{replay.current_sl:.6g} ({sl_diff:+.3f}%)")
                if cmp["verdict"] == "match":
                    cmp["verdict"] = "price_drift"
        if issues_extra:
            cmp["issues"] = issues_extra + cmp["issues"]
            cmp["verdict"] = "mismatch"
        result.update(cmp)
        result["notes"] = notes
        return result
