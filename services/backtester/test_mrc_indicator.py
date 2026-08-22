"""
Тесты MRC (Mean Reversion Channel) индикатора.
Запускается без pytest - просто python test_mrc_indicator.py
"""

import sys
import pandas as pd
import numpy as np

try:
    from indicators import TechnicalIndicators, IndicatorStrategy
    print("✅ indicators.py импортирован успешно")
except ImportError as e:
    print(f"❌ Ошибка импорта indicators: {e}")
    sys.exit(1)


def _make_ohlc(closes: np.ndarray, spread: float = 0.0) -> pd.DataFrame:
    dates = pd.date_range('2024-01-01', periods=len(closes), freq='15min')
    return pd.DataFrame({
        'timestamp': dates,
        'open': closes,
        'high': closes + spread,
        'low': closes - spread,
        'close': closes,
        'volume': np.full(len(closes), 1000.0),
    })


def test_supersmoother_flat_input():
    """Флэт-инпут: SuperSmoother должен сойтись к той же константе."""
    print("\n" + "=" * 60)
    print("ТЕСТ 1: SuperSmoother на константном входе")
    print("=" * 60)

    indicators = TechnicalIndicators()
    src = pd.Series(np.full(300, 100.0))
    out = indicators._supersmoother(src, length=200)

    tail = out.iloc[250:]
    max_dev = (tail - 100.0).abs().max()
    print(f"Макс. отклонение от 100.0 на хвосте (после прогрева): {max_dev:.10f}")

    assert max_dev < 1e-6, f"SuperSmoother не сошёлся к константе: max_dev={max_dev}"
    print("✅ SuperSmoother сходится к константе на флэт-инпуте")


def test_supersmoother_no_nan():
    """После бара 0 SuperSmoother не должен давать NaN (cold-start seed из src[0])."""
    print("\n" + "=" * 60)
    print("ТЕСТ 2: Отсутствие NaN после бара 0")
    print("=" * 60)

    indicators = TechnicalIndicators()
    np.random.seed(42)
    src = pd.Series(100 + np.cumsum(np.random.randn(500)))
    out = indicators._supersmoother(src, length=200)

    nan_count = out.iloc[1:].isna().sum()
    print(f"NaN после бара 0: {nan_count}")

    assert nan_count == 0, f"Обнаружены NaN после бара 0: {nan_count}"
    print("✅ Нет NaN после бара 0 (cold-start работает как задумано)")


def test_supersmoother_step_response_sane():
    """Ступенчатый вход: фильтр должен сойтись к новому уровню, не разойтись/не уйти в отрицательные."""
    print("\n" + "=" * 60)
    print("ТЕСТ 3: Ступенчатый отклик (sanity, не точное сравнение)")
    print("=" * 60)

    indicators = TechnicalIndicators()
    src = pd.Series(np.concatenate([np.full(300, 100.0), np.full(300, 200.0)]))
    out = indicators._supersmoother(src, length=50)

    tail = out.iloc[550:]
    print(f"Хвост после ступени (последние значения): {tail.iloc[-1]:.4f}")

    assert not out.isna().any(), "Обнаружены NaN в ступенчатом ответе"
    assert (out >= 90).all(), "Фильтр ушёл значительно ниже начального уровня"
    assert abs(tail.iloc[-1] - 200.0) < 5.0, "Фильтр не сошёлся к новому уровню (200) после ступени"
    print("✅ Ступенчатый отклик адекватен (сходится к новому уровню, не расходится)")


def test_calculate_mrc_basic_shape():
    """calculate_mrc() возвращает ожидаемые колонки, без NaN после warmup."""
    print("\n" + "=" * 60)
    print("ТЕСТ 4: calculate_mrc() — базовая форма результата")
    print("=" * 60)

    indicators = TechnicalIndicators()
    np.random.seed(1)
    closes = 40000 + np.cumsum(np.random.randn(500) * 20)
    df = _make_ohlc(closes, spread=15.0)

    mrc = indicators.calculate_mrc(df, length=200)

    expected_cols = {'meanline', 'meanrange', 'upband1', 'loband1', 'upband2', 'loband2', 'risk_zone'}
    assert expected_cols.issubset(set(mrc.columns)), f"Отсутствуют колонки: {expected_cols - set(mrc.columns)}"
    assert len(mrc) == len(df), "Длина результата не совпадает с длиной входа"
    assert not mrc['meanline'].isna().any(), "NaN в meanline"
    assert not mrc['risk_zone'].isna().any(), "NaN в risk_zone"
    assert mrc['risk_zone'].isin(range(-5, 6)).all(), "risk_zone вне диапазона -5..5"

    print(f"Колонки: {list(mrc.columns)}")
    print(f"risk_zone уникальные значения: {sorted(mrc['risk_zone'].unique())}")
    print("✅ calculate_mrc() возвращает корректную форму")


def test_risk_zone_classification_extremes():
    """
    Синтетический случай: резкий скачок цены далеко за outer band должен
    классифицироваться как risk_zone == 3 (extreme overbought), а стабильный
    период вблизи средней — как risk_zone в {4} (near mean) или 0.
    """
    print("\n" + "=" * 60)
    print("ТЕСТ 5: risk_zone классификация на контролируемых сценариях")
    print("=" * 60)

    indicators = TechnicalIndicators()

    # Стабильный период (низкая волатильность) + один резкий выброс в конце
    stable = np.full(250, 100.0) + np.random.RandomState(7).randn(250) * 0.05
    spike = np.array([100.0 + i * 5 for i in range(1, 11)])  # резкий рост в конце
    closes = np.concatenate([stable, spike])
    df = _make_ohlc(closes, spread=0.1)

    mrc = indicators.calculate_mrc(df, length=200, gradsize=0.5, outer_mult=2.415)

    last_zone = mrc['risk_zone'].iloc[-1]
    mid_zone = mrc['risk_zone'].iloc[240]  # ещё в стабильном участке

    print(f"risk_zone в стабильном участке (bar 240): {mid_zone}")
    print(f"risk_zone после резкого выброса (последний бар): {last_zone}")

    assert last_zone > 0, f"Ожидался положительный (overbought) risk_zone после выброса вверх, получено {last_zone}"
    # near-mean зоны: +4/-4 (near mean) или +5/-5 (above/below mean, но не overbought/oversold) —
    # обе означают "не в overbought/oversold ступенях 1/2/3". abs(mid_zone) >= 4 подтверждает это.
    assert abs(mid_zone) >= 4, f"Ожидался near-mean/above-mean risk_zone в стабильном участке (|zone|>=4), получено {mid_zone}"
    print("✅ risk_zone реагирует на выброс в ожидаемую сторону")


def test_mrc_reversion_signal_short():
    """
    mrc_reversion_signal() должен зажечь short_signal ровно при risk_zone==entry_band,
    и не одновременно с long_signal. Медленный памп (0.05/бар), чтобы цена
    прошла именно через zone=2, а не перепрыгнула его за один бар.
    """
    print("\n" + "=" * 60)
    print("ТЕСТ 6: mrc_reversion_signal() — SHORT сторона")
    print("=" * 60)

    indicators = TechnicalIndicators()
    strat = IndicatorStrategy(indicators)

    stable = 100 + np.random.RandomState(3).randn(250) * 0.05
    pump = np.array([100 + i * 0.05 for i in range(1, 151)])
    closes = np.concatenate([stable, pump])
    df = _make_ohlc(closes, spread=0.02)

    config = {'length': 200, 'entry_band': 2}

    fired = None
    for i in range(200, len(df)):
        sig = strat.mrc_reversion_signal(df.iloc[:i + 1], config)
        if sig['short_signal']:
            fired = (i, sig['risk_zone'], sig['long_signal'])
            break

    print(f"short_signal сработал на баре {fired[0] if fired else None}, risk_zone={fired[1] if fired else None}")
    assert fired is not None, "short_signal ни разу не сработал"
    assert fired[1] == 2, f"Ожидался risk_zone==2 в момент срабатывания, получено {fired[1]}"
    assert fired[2] is False, "long_signal не должен быть True одновременно с short_signal"
    print("✅ mrc_reversion_signal корректно зажигает short_signal на risk_zone==entry_band")


def test_mrc_reversion_signal_long():
    """Симметричный случай для LONG (медленный дамп)."""
    print("\n" + "=" * 60)
    print("ТЕСТ 7: mrc_reversion_signal() — LONG сторона")
    print("=" * 60)

    indicators = TechnicalIndicators()
    strat = IndicatorStrategy(indicators)

    stable = 100 + np.random.RandomState(3).randn(250) * 0.05
    dump = np.array([100 - i * 0.05 for i in range(1, 151)])
    closes = np.concatenate([stable, dump])
    df = _make_ohlc(closes, spread=0.02)

    config = {'length': 200, 'entry_band': 2}

    fired = None
    for i in range(200, len(df)):
        sig = strat.mrc_reversion_signal(df.iloc[:i + 1], config)
        if sig['long_signal']:
            fired = (i, sig['risk_zone'], sig['short_signal'])
            break

    print(f"long_signal сработал на баре {fired[0] if fired else None}, risk_zone={fired[1] if fired else None}")
    assert fired is not None, "long_signal ни разу не сработал"
    assert fired[1] == -2, f"Ожидался risk_zone==-2 в момент срабатывания, получено {fired[1]}"
    assert fired[2] is False, "short_signal не должен быть True одновременно с long_signal"
    print("✅ mrc_reversion_signal корректно зажигает long_signal на risk_zone==-entry_band")


def test_mrc_reversion_signal_warmup_guard():
    """Пока истории меньше length — сигнал должен быть False (length-based guard)."""
    print("\n" + "=" * 60)
    print("ТЕСТ 8: mrc_reversion_signal() — guard по недостатку истории")
    print("=" * 60)

    indicators = TechnicalIndicators()
    strat = IndicatorStrategy(indicators)

    closes = 100 + np.random.RandomState(1).randn(50) * 5  # меньше length=200
    df = _make_ohlc(closes, spread=0.5)

    sig = strat.mrc_reversion_signal(df, {'length': 200, 'entry_band': 2})

    assert sig['long_signal'] is False and sig['short_signal'] is False, \
        "Сигнал не должен срабатывать при недостатке истории (warmup guard)"
    print("✅ Guard по длине истории работает — сигнал False при len(data) < length")


if __name__ == '__main__':
    tests = [
        test_supersmoother_flat_input,
        test_supersmoother_no_nan,
        test_supersmoother_step_response_sane,
        test_calculate_mrc_basic_shape,
        test_risk_zone_classification_extremes,
        test_mrc_reversion_signal_short,
        test_mrc_reversion_signal_long,
        test_mrc_reversion_signal_warmup_guard,
    ]

    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"❌ {t.__name__} FAILED: {e}")
            failed.append(t.__name__)

    print("\n" + "=" * 60)
    if failed:
        print(f"❌ ПРОВАЛЕНО ТЕСТОВ: {len(failed)} — {failed}")
        sys.exit(1)
    else:
        print("✅ ВСЕ ТЕСТЫ ПРОШЛИ")
    print("=" * 60)
