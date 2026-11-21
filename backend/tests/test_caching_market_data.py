"""Кэш свечей пакетной сверки: монета качается один раз, срезы — из кэша."""
from unittest.mock import AsyncMock

import pytest

from app.adapters.caching_market_data import CachingMarketData


def _candles(start, end, step=60_000):
    return [{"timestamp": t, "close": 1.0} for t in range(start, end + 1, step)]


@pytest.mark.asyncio
async def test_range_fetched_once_then_sliced():
    market = AsyncMock()
    market.get_klines_range = AsyncMock(side_effect=lambda s, i, a, b: _candles(a, b))
    cache = CachingMarketData(market)
    full = await cache.get_klines_range("SOLUSDT", "1", 0, 600_000)
    part = await cache.get_klines_range("SOLUSDT", "1", 120_000, 300_000)
    assert len(full) == 11 and [c["timestamp"] for c in part] == [120_000, 180_000, 240_000, 300_000]
    assert cache.fetches == 1
    await cache.get_klines_range("ETHUSDT", "1", 0, 60_000)  # другая монета — свой запрос
    await cache.get_klines_range("SOLUSDT", "1", 480_000, 900_000)  # вышли за покрытое — дозапрос
    assert cache.fetches == 3
    assert len(await cache.get_klines_range("SOLUSDT", "1", 0, 900_000)) == 16


@pytest.mark.asyncio
async def test_partial_answer_covers_only_what_came():
    """Биржа отдала не весь длинный диапазон — непокрытое начало потом дозапрашивается."""
    market = AsyncMock()
    market.get_klines_range = AsyncMock(side_effect=lambda s, i, a, b: _candles(max(a, 300_000), b))
    cache = CachingMarketData(market)
    await cache.get_klines_range("SOLUSDT", "1", 0, 600_000)
    await cache.get_klines_range("SOLUSDT", "1", 0, 120_000)
    assert cache.fetches == 2
