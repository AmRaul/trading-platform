from typing import List, Dict, Optional
from datetime import datetime
from app.domain.screener.entities import ScreenerCandidate


class VolatilityAnalyzer:
    """Pure domain logic — calculates volatility metrics from OHLCV candles."""

    CANDLE_WINDOW = 20    # свечей для расчёта среднего размера
    ATR_PERIOD = 14
    VOLATILITY_THRESHOLD = 0.5  # % минимальный средний размер свечи

    def analyze(
        self,
        symbol: str,
        candles_1m: List[Dict],
        ticker: Dict,
        funding_rate: float = 0.0,
        candles_1h: List[Dict] = None,
    ) -> Optional[ScreenerCandidate]:
        """
        Returns ScreenerCandidate if symbol passes volatility threshold, else None.
        candles_1m: list of {open, high, low, close, volume, timestamp}, newest last.
        candles_1h: last 2 closed 1h candles for volume_1h calculation.
        """
        if len(candles_1m) < self.ATR_PERIOD + 1:
            return None

        avg_candle_pct = self._avg_candle_size(candles_1m[-self.CANDLE_WINDOW:])
        if avg_candle_pct < self.VOLATILITY_THRESHOLD:
            return None

        atr = self._atr(candles_1m[-(self.ATR_PERIOD + 1):])
        volume_24h = float(ticker.get("turnover24h", 0))
        last_price = float(ticker.get("lastPrice", 0))
        price_change_24h_pct = float(ticker.get("price24hPcnt", 0)) * 100
        high_24h = float(ticker.get("highPrice24h", 0))
        low_24h = float(ticker.get("lowPrice24h", 0))
        open_interest = float(ticker.get("openInterestValue", 0))

        # Volume last closed 1h candle (index 1 = prev closed, index 0 = current forming)
        volume_1h = 0.0
        if candles_1h and len(candles_1h) >= 2:
            volume_1h = float(candles_1h[1].get("volume", 0))

        direction = "FLAT"
        if price_change_24h_pct > 1.0:
            direction = "LONG"
        elif price_change_24h_pct < -1.0:
            direction = "SHORT"

        price_range_pct = None
        if high_24h > low_24h:
            price_range_pct = round((last_price - low_24h) / (high_24h - low_24h) * 100, 1)

        return ScreenerCandidate(
            symbol=symbol,
            avg_candle_size_pct=round(avg_candle_pct, 4),
            atr=round(atr, 6),
            volume_24h=volume_24h,
            volume_7d_avg=0.0,
            volume_ratio=0.0,
            volume_1h=volume_1h,
            funding_rate=funding_rate,
            price_change_24h_pct=round(price_change_24h_pct, 2),
            high_24h=high_24h,
            low_24h=low_24h,
            open_interest=open_interest,
            direction=direction,
            price_range_pct=price_range_pct,
            last_price=last_price,
            scanned_at=datetime.utcnow(),
        )

    def _avg_candle_size(self, candles: List[Dict]) -> float:
        """Average (High - Low) / Low * 100 across candles."""
        if not candles:
            return 0.0
        sizes = []
        for c in candles:
            low = c["low"]
            if low > 0:
                sizes.append((c["high"] - low) / low * 100)
        return sum(sizes) / len(sizes) if sizes else 0.0

    def _atr(self, candles: List[Dict]) -> float:
        """ATR(14) — average true range over last 14 candles."""
        if len(candles) < 2:
            return 0.0
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i]["high"]
            low = candles[i]["low"]
            prev_close = candles[i - 1]["close"]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            true_ranges.append(tr)
        period = min(self.ATR_PERIOD, len(true_ranges))
        return sum(true_ranges[-period:]) / period
