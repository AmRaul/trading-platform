#!/usr/bin/env python3
"""
Главный модуль для запуска бэктестирования алгоритмических стратегий

Использование:
    python main.py                          # Использует config.json
    python main.py --config my_config.json # Использует указанный конфиг
    python main.py --help                   # Показывает справку
"""

import argparse
import sys
import os
from pathlib import Path

# Добавляем текущую директорию в путь для импорта модулей
sys.path.append(str(Path(__file__).parent))

from backtester import Backtester
from reporter import BacktestReporter

def create_sample_data():
    """
    Создает образец данных для тестирования
    """
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta
    
    print("Создание образца данных для тестирования...")
    
    # Создаем директорию для данных
    os.makedirs("data", exist_ok=True)
    
    # Параметры для генерации данных
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2023, 12, 31)
    
    # Генерируем временные метки (15-минутные интервалы)
    timestamps = []
    current_time = start_date
    while current_time <= end_date:
        timestamps.append(current_time)
        current_time += timedelta(minutes=15)
    
    # Генерируем реалистичные OHLCV данные
    np.random.seed(42)  # Для воспроизводимости
    
    n_points = len(timestamps)
    base_price = 30000  # Начальная цена BTC
    
    # Генерируем случайное блуждание с трендом
    returns = np.random.normal(0.0001, 0.02, n_points)  # Небольшой положительный тренд
    
    # Создаем цены закрытия
    closes = [base_price]
    for i in range(1, n_points):
        new_price = closes[-1] * (1 + returns[i])
        closes.append(max(new_price, 100))  # Минимальная цена 100
    
    # Генерируем OHLV на основе цен закрытия
    data = []
    for i, (timestamp, close) in enumerate(zip(timestamps, closes)):
        if i == 0:
            open_price = close
        else:
            open_price = closes[i-1]
        
        # Генерируем high и low с некоторой волатильностью
        volatility = abs(np.random.normal(0, 0.01))
        high = max(open_price, close) * (1 + volatility)
        low = min(open_price, close) * (1 - volatility)
        
        # Убеждаемся, что OHLC логически корректны
        high = max(high, open_price, close)
        low = min(low, open_price, close)
        
        # Генерируем объем
        volume = np.random.uniform(10, 1000)
        
        data.append({
            'timestamp': timestamp,
            'open': round(open_price, 2),
            'high': round(high, 2),
            'low': round(low, 2),
            'close': round(close, 2),
            'volume': round(volume, 2)
        })
    
    # Сохраняем в CSV
    df = pd.DataFrame(data)
    df.to_csv("data/BTCUSDT_15m.csv", index=False)
    
    print(f"Создан файл данных: data/BTCUSDT_15m.csv")
    print(f"Период: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
    print(f"Записей: {len(data)}")
    print(f"Диапазон цен: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

def main():
    """Основная функция"""
    parser = argparse.ArgumentParser(
        description='Бэктестер алгоритмических торговых стратегий',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python main.py                          # Базовый запуск с config.json
  python main.py --config my_config.json  # Использование своего конфига
  python main.py --create-sample-data     # Создание образца данных
  python main.py --report-only results.json  # Только генерация отчета
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='config.json',
        help='Путь к файлу конфигурации (по умолчанию: config.json)'
    )
    
    parser.add_argument(
        '--strategy',
        type=str,
        choices=['conservative_long', 'conservative_short', 'immediate_long', 'high_leverage_test', 
                'altcoin_simple_dca', 'aggressive_martingale', 'fibonacci_dca', 'short_strategy', 
                'risk_based_sizing', 'atr_based_steps', 'fixed_amount_strategy',
                'trend_momentum_strategy', 'volatility_bounce_strategy', 'momentum_trend_strategy'],
        help='Выбрать готовую стратегию из примеров'
    )
    
    parser.add_argument(
        '--create-sample-data',
        action='store_true',
        help='Создать образец данных для тестирования'
    )
    
    parser.add_argument(
        '--report-only',
        type=str,
        help='Создать отчет из существующих результатов (путь к JSON файлу с результатами)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Подробный вывод процесса бэктестирования'
    )
    
    parser.add_argument(
        '--save-results',
        action='store_true',
        help='Сохранить результаты в JSON файл'
    )
    
    parser.add_argument(
        '--generate-report',
        action='store_true',
        help='Сгенерировать полный отчет с графиками'
    )
    
    parser.add_argument(
        '--download-data',
        action='store_true',
        help='Загрузить данные с биржи и сохранить в CSV'
    )
    
    parser.add_argument(
        '--exchange',
        type=str,
        default='binance',
        help='Биржа для загрузки данных (по умолчанию: binance)'
    )
    
    parser.add_argument(
        '--symbol-api',
        type=str,
        default='BTC/USDT',
        help='Торговая пара для API (например: BTC/USDT)'
    )
    
    parser.add_argument(
        '--timeframe-api',
        type=str,
        default='1h',
        help='Таймфрейм для API (1m, 5m, 15m, 1h, 4h, 1d)'
    )
    
    parser.add_argument(
        '--list-exchanges',
        action='store_true',
        help='Показать список доступных бирж'
    )
    
    parser.add_argument(
        '--exchange-info',
        type=str,
        help='Показать информацию о бирже'
    )

    # Optimization arguments
    parser.add_argument(
        '--optimize',
        action='store_true',
        help='Запустить оптимизацию параметров стратегии'
    )

    parser.add_argument(
        '--optimization-config',
        type=str,
        help='Путь к конфигу оптимизации (JSON файл)'
    )

    parser.add_argument(
        '--user-id',
        type=str,
        help='Telegram user ID для уведомлений и авторизации'
    )

    parser.add_argument(
        '--n-trials',
        type=int,
        default=100,
        help='Количество trials для оптимизации (по умолчанию: 100)'
    )

    args = parser.parse_args()
    
    # Создание образца данных
    if args.create_sample_data:
        create_sample_data()
        return
    
    # Показать список бирж
    if args.list_exchanges:
        from data_loader import DataLoader
        loader = DataLoader()
        exchanges = loader.get_available_exchanges()
        
        if exchanges:
            print("Доступные биржи с поддержкой OHLCV:")
            for i, exchange in enumerate(exchanges, 1):
                print(f"{i:2d}. {exchange}")
            print(f"\nВсего: {len(exchanges)} бирж")
        else:
            print("CCXT не установлен или нет доступных бирж")
        return
    
    # Показать информацию о бирже
    if args.exchange_info:
        from data_loader import DataLoader
        loader = DataLoader()
        info = loader.get_exchange_info(args.exchange_info)
        
        if 'error' in info:
            print(f"Ошибка: {info['error']}")
        else:
            print(f"Информация о бирже: {info['name']}")
            print(f"Страны: {', '.join(info.get('countries', ['N/A']))}")
            print(f"Поддержка OHLCV: {'Да' if info['has_ohlcv'] else 'Нет'}")
            print(f"Количество торговых пар: {info['symbols_count']}")
            print(f"Лимит запросов: {info['rate_limit']} мс")
            print(f"Доступные таймфреймы: {', '.join(info['timeframes'])}")
            print(f"Популярные пары: {', '.join(info['popular_symbols'])}")
        return
    
    # Загрузка данных с API
    if args.download_data:
        from data_loader import DataLoader
        
        try:
            loader = DataLoader()
            
            # Определяем даты
            from datetime import datetime, timedelta
            
            start_date = input("Начальная дата (YYYY-MM-DD) или Enter для последних 30 дней: ").strip()
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            end_date = input("Конечная дата (YYYY-MM-DD) или Enter для текущей даты: ").strip()
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            
            print(f"\nЗагрузка данных:")
            print(f"Биржа: {args.exchange}")
            print(f"Символ: {args.symbol_api}")
            print(f"Таймфрейм: {args.timeframe_api}")
            print(f"Период: {start_date} - {end_date}")
            
            # Загружаем данные
            data = loader.load_from_api(
                symbol=args.symbol_api,
                timeframe=args.timeframe_api,
                start_date=start_date,
                end_date=end_date,
                exchange=args.exchange
            )
            
            # Сохраняем в CSV
            filename = loader.save_to_csv()
            
            print(f"\n✅ Данные успешно загружены и сохранены!")
            print(f"Файл: {filename}")
            print(f"Записей: {len(data)}")
            
        except Exception as e:
            print(f"❌ Ошибка при загрузке данных: {e}")

        return

    # Optimization mode
    if args.optimize:
        print("🔬 Запуск оптимизации параметров стратегии...")

        # Check user_id
        if not args.user_id:
            print("❌ Ошибка: --user-id обязателен для оптимизации")
            print("Пример: python main.py --optimize --optimization-config optimization_config.json --user-id YOUR_TELEGRAM_ID")
            return

        # Load optimization config
        if not args.optimization_config:
            print("❌ Ошибка: --optimization-config обязателен для оптимизации")
            print("Пример: python main.py --optimize --optimization-config optimization_config_example.json --user-id 123456")
            return

        if not os.path.exists(args.optimization_config):
            print(f"❌ Ошибка: файл {args.optimization_config} не найден")
            return

        try:
            import json
            with open(args.optimization_config, 'r', encoding='utf-8') as f:
                opt_config = json.load(f)

            base_config = opt_config.get('base_config')
            optimization_params = opt_config.get('optimization_params')

            if not base_config or not optimization_params:
                print("❌ Ошибка: конфиг должен содержать base_config и optimization_params")
                return

            # Import optimizer
            from optimizer import OptunaOptimizer

            # Setup notification callback
            try:
                import sys
                sys.path.append('market-analytics/bot')
                from notifications import send_optimization_notification
                notification_callback = send_optimization_notification
                print(f"✅ Уведомления Telegram включены для user_id: {args.user_id}")
            except Exception as e:
                print(f"⚠️  Предупреждение: не удалось загрузить модуль уведомлений: {e}")
                notification_callback = None

            # Create optimizer
            optimizer = OptunaOptimizer(
                base_config=base_config,
                optimization_params=optimization_params,
                n_trials=args.n_trials,
                max_parallel_backtests=4,
                optimization_metric=opt_config.get('optimization_settings', {}).get('optimization_metric', 'custom_score'),
                notification_callback=notification_callback,
                user_id=args.user_id
            )

            print(f"📊 Конфигурация:")
            print(f"  - Символ: {base_config.get('symbol', 'Unknown')}")
            print(f"  - Trials: {args.n_trials}")
            print(f"  - Параметры: {len(optimization_params)}")
            print(f"  - Метрика: {optimizer.optimization_metric}")
            print(f"\n⏱️  Примерное время: ~{optimizer._estimate_time()} минут\n")

            # Run optimization
            results = optimizer.optimize()

            # Display results
            print("\n" + "=" * 60)
            print("🏆 РЕЗУЛЬТАТЫ ОПТИМИЗАЦИИ")
            print("=" * 60)
            print(f"\nЛучший score: {results['best_score']:.2f}")
            print(f"\nЛучшие параметры:")
            for key, value in results['best_params'].items():
                print(f"  - {key}: {value}")

            if results['best_results']:
                stats = results['best_results'].get('basic_stats', {})
                print(f"\nМетрики лучшей конфигурации:")
                print(f"  - Успешных сделок: {stats.get('winning_trades', 0)}")
                print(f"  - Win Rate: {stats.get('win_rate', 0):.1f}%")
                print(f"  - Доходность: {stats.get('total_return', 0):.2f}%")
                print(f"  - Profit Factor: {results['best_results'].get('advanced_metrics', {}).get('profit_factor', 0):.2f}")

            # Save results
            from database import save_optimization_result
            import uuid
            task_id = str(uuid.uuid4())

            try:
                save_optimization_result(task_id, {
                    'status': 'completed',
                    'n_trials': args.n_trials,
                    'best_params': results['best_params'],
                    'best_score': results['best_score'],
                    'best_config': results['best_config'],
                    'best_results': results['best_results'],
                    'all_trials': results['all_trials'],
                    'duration_minutes': results['duration_minutes'],
                    'user_id': args.user_id,
                    'optimization_metric': optimizer.optimization_metric
                })
                print(f"\n💾 Результаты сохранены в БД (task_id: {task_id})")
            except Exception as e:
                print(f"\n⚠️  Не удалось сохранить в БД: {e}")

            # Export to JSON
            export_path = f"results/optimization_{task_id[:8]}.json"
            os.makedirs('results', exist_ok=True)
            optimizer.export_results(export_path)
            print(f"💾 Экспорт в JSON: {export_path}")

            print("\n✅ Оптимизация завершена!")

        except Exception as e:
            print(f"❌ Ошибка при оптимизации: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()

        return

    # Генерация отчета из существующих результатов
    if args.report_only:
        if not os.path.exists(args.report_only):
            print(f"Ошибка: файл {args.report_only} не найден")
            return
        
        import json
        with open(args.report_only, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        reporter = BacktestReporter(results)
        reporter.generate_full_report()
        return
    
    # Обрабатываем выбор готовой стратегии
    if args.strategy:
        if not os.path.exists('config_examples.json'):
            print("Ошибка: файл config_examples.json не найден")
            return
        
        import json
        with open('config_examples.json', 'r', encoding='utf-8') as f:
            examples = json.load(f)
        
        if args.strategy not in examples:
            print(f"Ошибка: стратегия {args.strategy} не найдена")
            return
        
        config_dict = examples[args.strategy]
        print(f"Используется готовая стратегия: {args.strategy}")
    else:
        # Проверяем наличие файла конфигурации
        if not os.path.exists(args.config):
            print(f"Ошибка: файл конфигурации {args.config} не найден")
            print("Используйте --create-sample-data для создания образца данных и конфигурации")
            print("Или выберите готовую стратегию с помощью --strategy")
            return
        config_dict = None
    
    try:
        print("🚀 Запуск бэктестера...")
        if args.strategy:
            print(f"Стратегия: {args.strategy}")
        else:
            print(f"Конфигурация: {args.config}")
        
        # Создаем и запускаем бэктестер
        if config_dict:
            backtester = Backtester(config_dict=config_dict)
        else:
            backtester = Backtester(config_path=args.config)
        results = backtester.run_backtest(verbose=args.verbose)
        
        # Сохраняем результаты если запрошено
        if args.save_results:
            filename = backtester.save_results()
            print(f"\n💾 Результаты сохранены в: {filename}")
            print(f"Для проверки расчетов запустите: python debug_calculations.py {filename}")
        
        # Генерируем отчет если запрошено
        if args.generate_report:
            print("\n📊 Генерация полного отчета...")
            reporter = BacktestReporter(results)
            reporter.generate_full_report()
        
        # Показываем краткую статистику по лучшим/худшим сделкам
        if results['trade_history']:
            reporter = BacktestReporter(results)
            reporter.print_top_trades(5)
            
            # Показываем метрики риска
            risk_metrics = reporter.get_risk_metrics()
            if risk_metrics:
                print("\n📊 МЕТРИКИ РИСКА:")
                print("-" * 40)
                print(f"Волатильность (год): {risk_metrics['volatility']*100:.2f}%")
                print(f"VaR 95%: {risk_metrics['var_95']*100:.2f}%")
                print(f"VaR 99%: {risk_metrics['var_99']*100:.2f}%")
                print(f"Calmar Ratio: {risk_metrics['calmar_ratio']:.2f}")
                print(f"Recovery Factor: {risk_metrics['recovery_factor']:.2f}")
            
            # Показываем информацию о незавершенных сделках
            open_trades = [t for t in results['trade_history'] if t['reason'] == 'end_of_data']
            if open_trades:
                print(f"\n⚠️  НЕЗАВЕРШЕННЫЕ СДЕЛКИ:")
                print("-" * 40)
                for i, trade in enumerate(open_trades, 1):
                    print(f"{i}. {trade['symbol']} | Вход: ${trade['entry_price']:.4f} | "
                          f"Средняя цена: ${trade.get('average_price', trade['entry_price']):.4f} | "
                          f"Количество: {trade['quantity']:.6f} | "
                          f"DCA ордеров: {trade['dca_orders_count']}")
                print(f"* Эти сделки не были закрыты по стратегии и исключены из статистики")
        
        print("\n✅ Бэктест завершен успешно!")
        
    except FileNotFoundError as e:
        print(f"❌ Ошибка: файл не найден - {e}")
        print("Проверьте путь к файлу данных в конфигурации")
        if "data/" in str(e):
            print("Используйте --create-sample-data для создания образца данных")
    
    except Exception as e:
        print(f"❌ Ошибка при выполнении бэктеста: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main() 