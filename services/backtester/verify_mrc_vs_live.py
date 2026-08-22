"""
Разовый скрипт сверки: сравнивает реальные сделки живого BTC-бота (backend БД)
с моментами, когда Python-перенос MRC-индикатора даёт risk_zone == ±entry_band
на тех же исторических барах.

НЕ автоматический pass/fail — печатает таблицу для ручного просмотра.
НЕ пишет ничего в БД (только SELECT).
НЕ встроен в main.py/web_app.py — запускается напрямую:

    python verify_mrc_vs_live.py --bot-id 5 --start-date 2024-01-01 --end-date 2024-12-31

По умолчанию использует docker-compose дефолты (trading/trading123@localhost:5432/trading_db).
Задать другую строку подключения: --db-url postgresql://user:pass@host:port/dbname
"""

import argparse
import sys

import pandas as pd
from sqlalchemy import create_engine, text

from data_loader import DataLoader
from indicators import TechnicalIndicators

DEFAULT_DB_URL = "postgresql://trading:trading123@localhost:5432/trading_db"


def fetch_real_trades(db_url: str, bot_id: int, start_date: str, end_date: str) -> pd.DataFrame:
    """Read-only: тянет реальные сделки бота из backend БД (только SELECT)."""
    db_url = db_url.replace('+asyncpg', '')
    engine = create_engine(db_url)

    query = text("""
        SELECT t.id, t.symbol, t.side, t.entry_price, t.average_price, t.exit_price,
               t.exit_reason, t.pnl, t.pnl_percent, t.total_orders, t.opened_at, t.closed_at
        FROM trades t
        WHERE t.bot_id = :bot_id
          AND t.opened_at BETWEEN :start_date AND :end_date
        ORDER BY t.opened_at
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'bot_id': bot_id, 'start_date': start_date, 'end_date': end_date
        })
        rows = result.fetchall()
        columns = result.keys()

    engine.dispose()
    return pd.DataFrame(rows, columns=columns)


def fetch_bot_info(db_url: str, bot_id: int) -> dict:
    """Read-only: тянет symbol/side бота, чтобы знать что грузить с биржи."""
    db_url = db_url.replace('+asyncpg', '')
    engine = create_engine(db_url)

    query = text("SELECT id, name, symbol, side FROM bots WHERE id = :bot_id")
    with engine.connect() as conn:
        row = conn.execute(query, {'bot_id': bot_id}).fetchone()

    engine.dispose()
    if row is None:
        raise ValueError(f"Bot id={bot_id} не найден в БД")
    return dict(row._mapping)


def find_bar_at_or_before(ohlcv: pd.DataFrame, ts: pd.Timestamp) -> int:
    """Индекс последнего закрытого бара на момент или до ts."""
    idx = ohlcv[ohlcv['timestamp'] <= ts].index
    if len(idx) == 0:
        return None
    return idx[-1]


def main():
    parser = argparse.ArgumentParser(
        description="Сверка реальных сделок BTC-бота с MRC-сигналом на тех же исторических барах"
    )
    parser.add_argument('--bot-id', type=int, required=True, help='ID бота из таблицы bots')
    parser.add_argument('--start-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', type=str, required=True, help='YYYY-MM-DD')
    parser.add_argument('--db-url', type=str, default=DEFAULT_DB_URL, help='Строка подключения к backend БД')
    parser.add_argument('--length', type=int, default=200, help='Период MRC (должен совпадать с live-настройкой)')
    parser.add_argument('--entry-band', type=int, default=2, help='Полоса входа (должна совпадать с live-настройкой)')
    parser.add_argument('--timeframe', type=str, default='15m')
    args = parser.parse_args()

    print(f"Подключение к backend БД: {args.db_url.split('@')[-1]}")

    try:
        bot = fetch_bot_info(args.db_url, args.bot_id)
    except Exception as e:
        print(f"❌ Не удалось получить информацию о боте: {e}")
        sys.exit(1)

    print(f"Бот: {bot['name']} | symbol={bot['symbol']} | side={bot['side']}")

    try:
        trades = fetch_real_trades(args.db_url, args.bot_id, args.start_date, args.end_date)
    except Exception as e:
        print(f"❌ Не удалось получить реальные сделки: {e}")
        sys.exit(1)

    if len(trades) == 0:
        print("⚠️  Реальных сделок в указанном диапазоне не найдено — нечего сверять.")
        sys.exit(0)

    print(f"Найдено реальных сделок: {len(trades)}")

    # Запас в length баров ДО первой сделки, чтобы канал успел прогреться
    # к моменту первой реальной сделки (иначе первые сделки ложно попадут
    # в warmup-guard и будут выглядеть как несовпадение).
    bar_minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60, '4h': 240, '1d': 1440}.get(args.timeframe, 15)
    warmup_start = pd.Timestamp(trades['opened_at'].min()) - pd.Timedelta(minutes=bar_minutes * args.length)

    symbol_api = bot['symbol']
    if not symbol_api.endswith('USDT') and '/' not in symbol_api:
        symbol_api = symbol_api  # оставляем как есть, DataLoader сам нормализует
    symbol_api = symbol_api.replace('USDT', '/USDT') if '/' not in symbol_api else symbol_api

    print(f"Загрузка OHLCV: {symbol_api} {args.timeframe} с {warmup_start.date()} по {args.end_date}...")

    loader = DataLoader()
    ohlcv = loader.load_from_api(
        symbol=symbol_api,
        timeframe=args.timeframe,
        start_date=str(warmup_start.date()),
        end_date=args.end_date,
        exchange='binance',
        market_type='futures',
    )

    print(f"Загружено {len(ohlcv)} баров. Расчёт MRC...")

    indicators = TechnicalIndicators()
    mrc = indicators.calculate_mrc(ohlcv, length=args.length)

    print("\n" + "=" * 100)
    print(f"{'opened_at':<20} {'side':<6} {'entry_price':>12} {'avg_price':>12} "
          f"{'risk_zone@bar':>14} {'meanline':>12} {'upband2':>12} {'loband2':>12}")
    print("=" * 100)

    matched_band = 0
    for _, trade in trades.iterrows():
        opened_at = pd.Timestamp(trade['opened_at'])
        bar_idx = find_bar_at_or_before(ohlcv, opened_at)

        if bar_idx is None:
            print(f"{str(opened_at):<20} {trade['side']:<6} {trade['entry_price']:>12.2f} "
                  f"{trade['average_price']:>12.2f} {'НЕТ ДАННЫХ':>14}")
            continue

        rz = int(mrc['risk_zone'].iloc[bar_idx])
        meanline = mrc['meanline'].iloc[bar_idx]
        upband2 = mrc['upband2'].iloc[bar_idx]
        loband2 = mrc['loband2'].iloc[bar_idx]

        if abs(rz) == args.entry_band:
            matched_band += 1

        print(f"{str(opened_at):<20} {trade['side']:<6} {trade['entry_price']:>12.2f} "
              f"{trade['average_price']:>12.2f} {rz:>14} {meanline:>12.2f} {upband2:>12.2f} {loband2:>12.2f}")

    print("=" * 100)
    print(f"\nИз {len(trades)} реальных сделок risk_zone==±{args.entry_band} "
          f"на баре входа совпал в {matched_band} случаях "
          f"({100*matched_band/len(trades):.1f}%).")

    # Информационно: сколько всего сигнальных баров было за период (не через
    # полный TradingStrategy, просто сколько раз risk_zone касался entry_band)
    total_signal_bars = int((mrc['risk_zone'].abs() == args.entry_band).sum())
    print(f"Всего баров с risk_zone==±{args.entry_band} за весь загруженный период: {total_signal_bars} "
          f"(бот мог не входить на каждом — например если уже в позиции)")


if __name__ == '__main__':
    main()
