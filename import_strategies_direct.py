#!/usr/bin/env python3
"""
Import strategy configurations from JSON files to PostgreSQL database (Direct SQL)
"""

import json
import os
import psycopg2
from pathlib import Path
from datetime import datetime

def import_json_strategies():
    """Import all valid strategy JSON files from directory to database"""

    # Database connection
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cursor = conn.cursor()

    imported = 0
    skipped = 0

    print("=" * 60)
    print("Strategy Import Utility (Direct SQL)")
    print("=" * 60)

    # Find JSON files
    json_files = [
        'ema_rsi_adx_crossover_15m_long.json',
        'ema_rsi_adx_crossover_15m_short.json',
        'ema_rsi_adx_crossover_test.json'
    ]

    for filename in json_files:
        try:
            print(f"\nProcessing: {filename}")

            # Read JSON
            with open(filename, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Generate strategy name
            strategy_name = filename.replace('_', ' ').replace('.json', '').title()

            # Check if exists
            cursor.execute(
                "SELECT COUNT(*) FROM backtester.strategy_configs WHERE name = %s",
                (strategy_name,)
            )
            if cursor.fetchone()[0] > 0:
                print(f"  ⚠️  Skipped: Already exists")
                skipped += 1
                continue

            # Extract metadata
            order_type = config.get('order_type', 'unknown')
            timeframe = config.get('timeframe', config.get('data_source', {}).get('timeframe', 'unknown'))
            symbol = config.get('data_source', {}).get('symbol', 'unknown')
            has_indicators = config.get('indicators', {}).get('enabled', False)
            strategy_type = config.get('indicators', {}).get('strategy_type', 'manual')

            # Description
            description = f"{order_type.upper()} strategy on {timeframe} using {strategy_type} indicators for {symbol}"

            # Tags as PostgreSQL array
            tags = ['imported', order_type]
            if has_indicators:
                tags.extend(['indicators', 'live-signals'])
            if timeframe:
                tags.append(timeframe)

            # Insert using direct SQL
            cursor.execute("""
                INSERT INTO backtester.strategy_configs (
                    name, description, config_json, tags,
                    created_at, updated_at, is_public, author
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
            """, (
                strategy_name,
                description,
                json.dumps(config),
                tags,  # PostgreSQL will handle the array
                datetime.utcnow(),
                datetime.utcnow(),
                False,
                'system'
            ))

            conn.commit()

            print(f"  ✅ Imported: {strategy_name}")
            print(f"     Type: {order_type} | TF: {timeframe} | Indicators: {has_indicators}")
            imported += 1

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            conn.rollback()

    cursor.close()
    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("Import Summary")
    print("=" * 60)
    print(f"✅ Successfully imported: {imported}")
    print(f"⚠️  Skipped: {skipped}")
    print("=" * 60)

    # List imported
    if imported > 0:
        print("\nVerifying import...")
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cursor = conn.cursor()
        cursor.execute("SELECT name, tags FROM backtester.strategy_configs ORDER BY created_at DESC LIMIT 10")
        for row in cursor.fetchall():
            print(f"  • {row[0]} - Tags: {row[1]}")
        cursor.close()
        conn.close()


if __name__ == '__main__':
    import_json_strategies()
