#!/usr/bin/env python3
"""
Import strategy configurations from JSON files to PostgreSQL database
"""

import json
import os
import sys
from pathlib import Path
from database import save_strategy_config, get_all_strategy_configs

def import_json_strategies(directory='.'):
    """
    Import all valid strategy JSON files from directory to database

    Args:
        directory: Directory to scan for JSON files (default: current directory)
    """
    imported = 0
    skipped = 0
    errors = 0

    # Get list of existing strategies to avoid duplicates
    existing_strategies = get_all_strategy_configs()
    existing_names = {config['name'] for config in existing_strategies}

    print("=" * 60)
    print("Strategy Import Utility")
    print("=" * 60)
    print(f"Scanning directory: {os.path.abspath(directory)}")
    print(f"Existing strategies in DB: {len(existing_names)}")
    print()

    # Find all JSON files
    json_files = list(Path(directory).glob('*.json'))

    # Filter out optimization configs and empty files
    strategy_files = []
    for json_file in json_files:
        if 'optimization_config' in json_file.name:
            continue
        if json_file.stat().st_size < 10:  # Skip empty files
            continue
        strategy_files.append(json_file)

    print(f"Found {len(strategy_files)} potential strategy files")
    print()

    for json_file in strategy_files:
        try:
            print(f"Processing: {json_file.name}")

            # Read JSON
            with open(json_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # Validate config structure
            if not isinstance(config, dict):
                print(f"  ⚠️  Skipped: Not a valid config object")
                skipped += 1
                continue

            # Check if it's a strategy config (has required fields)
            required_fields = ['order_type', 'data_source']
            if not all(field in config for field in required_fields):
                print(f"  ⚠️  Skipped: Missing required fields")
                skipped += 1
                continue

            # Generate strategy name from filename
            base_name = json_file.stem
            strategy_name = base_name.replace('_', ' ').title()

            # Check if already exists
            if strategy_name in existing_names:
                print(f"  ⚠️  Skipped: Strategy '{strategy_name}' already exists in DB")
                skipped += 1
                continue

            # Extract metadata
            order_type = config.get('order_type', 'unknown')
            timeframe = config.get('timeframe', config.get('data_source', {}).get('timeframe', 'unknown'))
            symbol = config.get('data_source', {}).get('symbol', 'unknown')

            # Check if indicators enabled (required for live signals)
            has_indicators = config.get('indicators', {}).get('enabled', False)
            strategy_type = config.get('indicators', {}).get('strategy_type', 'manual')

            # Generate description
            description = f"{order_type.upper()} strategy on {timeframe}"
            if has_indicators:
                description += f" using {strategy_type} indicators"
            description += f" for {symbol}"

            # Generate tags
            tags = ['imported']
            if has_indicators:
                tags.append('indicators')
                tags.append('live-signals')
            tags.append(order_type)
            if timeframe:
                tags.append(f'{timeframe}')

            # Save to database
            result = save_strategy_config(
                name=strategy_name,
                config=config,
                description=description,
                tags=tags
            )

            if result:
                print(f"  ✅ Imported: {strategy_name}")
                print(f"     Type: {order_type} | TF: {timeframe} | Indicators: {has_indicators}")
                imported += 1
            else:
                print(f"  ❌ Failed to save to database")
                errors += 1

        except json.JSONDecodeError as e:
            print(f"  ❌ Error: Invalid JSON - {str(e)}")
            errors += 1
        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            errors += 1

        print()

    # Summary
    print("=" * 60)
    print("Import Summary")
    print("=" * 60)
    print(f"✅ Successfully imported: {imported}")
    print(f"⚠️  Skipped: {skipped}")
    print(f"❌ Errors: {errors}")
    print(f"📊 Total in DB now: {len(existing_names) + imported}")
    print("=" * 60)

    return imported, skipped, errors


def list_imported_strategies():
    """List all strategies currently in database"""
    print("\n" + "=" * 60)
    print("Strategies in Database")
    print("=" * 60)

    configs = get_all_strategy_configs()

    if not configs:
        print("No strategies found in database")
        return

    for i, config in enumerate(configs, 1):
        name = config.get('name', 'Unnamed')
        order_type = config.get('order_type', 'N/A')
        tags = config.get('tags', [])
        has_indicators = 'indicators' in tags

        print(f"{i}. {name}")
        print(f"   Type: {order_type} | Indicators: {'✅' if has_indicators else '❌'}")
        print(f"   Tags: {', '.join(tags) if tags else 'none'}")
        print()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Import strategy configurations to database')
    parser.add_argument(
        '--directory',
        type=str,
        default='.',
        help='Directory to scan for JSON files (default: current directory)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all strategies in database'
    )

    args = parser.parse_args()

    if args.list:
        list_imported_strategies()
    else:
        imported, skipped, errors = import_json_strategies(args.directory)

        # Show imported strategies
        if imported > 0:
            list_imported_strategies()

        # Exit code
        sys.exit(0 if errors == 0 else 1)
