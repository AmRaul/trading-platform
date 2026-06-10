#!/usr/bin/env python3
"""
Веб-интерфейс для бэктестера алгоритмических стратегий
"""

from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
import base64
import io
import pandas as pd
import logging

from backtester import Backtester
from reporter import BacktestReporter
from data_loader import DataLoader
from visualizer import BacktestVisualizer

# PostgreSQL database layer
from database import (
    get_db_session,
    StrategyConfig,
    BacktestHistory,
    save_strategy_config,
    save_backtest_result,
    get_backtest_by_task_id,
    get_recent_backtests,
    get_all_strategy_configs,
    check_db_health,
    init_database,
    check_user_optimizer_access,
    get_optimization_by_task_id,
    get_recent_optimizations,
    save_optimization_result
)

# Optimization modules
from optimization_queue import global_optimization_queue
from functools import wraps

app = Flask(__name__)
app.secret_key = 'backtester_secret_key_change_in_production'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные для отслеживания задач
running_backtests = {}
backtest_results = {}
data_downloads = {}

# Helper functions
def get_csv_files_list():
    """Returns list of CSV files with metadata"""
    csv_files = []
    data_dir = Path('data')
    if data_dir.exists():
        for csv_file in data_dir.glob('*.csv'):
            try:
                df = pd.read_csv(csv_file)
                rows_count = len(df)
                date_range = None
                if 'timestamp' in df.columns and len(df) > 0:
                    start_date = pd.to_datetime(df['timestamp'].iloc[0]).strftime('%Y-%m-%d')
                    end_date = pd.to_datetime(df['timestamp'].iloc[-1]).strftime('%Y-%m-%d')
                    date_range = f"{start_date} - {end_date}"

                csv_files.append({
                    'path': str(csv_file),
                    'name': csv_file.name,
                    'date_range': date_range,
                    'rows': rows_count,
                    'size': csv_file.stat().st_size
                })
            except Exception as e:
                csv_files.append({
                    'path': str(csv_file),
                    'name': csv_file.name,
                    'date_range': None,
                    'rows': 0,
                    'size': csv_file.stat().st_size if csv_file.exists() else 0
                })
        csv_files.sort(key=lambda x: Path(x['path']).stat().st_mtime, reverse=True)
    return csv_files

# ============================================================================
# PostgreSQL database is now used via database.py
# SQLite code below is kept for reference but commented out
# ============================================================================

# # OLD SQLite CODE - COMMENTED OUT
# # Инициализация базы данных
# def init_database():
#     """Инициализирует базу данных SQLite"""
#     ...
#
# @contextmanager
# def get_db_connection():
#     """Контекстный менеджер для работы с базой данных"""
#     ...

# Инициализируем PostgreSQL базу данных при импорте модуля
print("[DATABASE] Initializing PostgreSQL connection...")
init_database()

class BacktestTask:
    def __init__(self, task_id, config):
        self.task_id = task_id
        self.config = config
        self.status = 'pending'
        self.progress = 0
        self.results = None
        self.error = None
        self.start_time = datetime.now()

class DataDownloadTask:
    def __init__(self, task_id, params):
        self.task_id = task_id
        self.params = params
        self.status = 'pending'
        self.progress = 0
        self.filename = None
        self.records_count = 0
        self.error = None
        self.start_time = datetime.now()

def run_backtest_async(task_id, config):
    """Запускает бэктест в отдельном потоке"""
    task = running_backtests[task_id]

    try:
        task.status = 'running'

        # Создаем бэктестер
        backtester = Backtester(config_dict=config)

        # Запускаем бэктест
        results = backtester.run_backtest(verbose=False)

        # Сохраняем результаты
        task.results = results
        task.status = 'completed'
        task.progress = 100

        # Сохраняем в глобальный кэш (для быстрого доступа)
        backtest_results[task_id] = results

        # Сохраняем в базу данных (для постоянного хранения)
        try:
            save_backtest_to_db(task_id, config, results)
            print(f"[BACKTEST] Результаты {task_id} сохранены в БД")
        except Exception as db_error:
            print(f"[BACKTEST ERROR] Не удалось сохранить в БД: {db_error}")

    except Exception as e:
        task.error = str(e)
        task.status = 'error'
        print(f"Ошибка в бэктесте {task_id}: {e}")

def download_data_async(task_id, params):
    """Загружает данные с биржи в отдельном потоке"""
    task = data_downloads[task_id]

    try:
        task.status = 'running'
        task.progress = 10

        exchange = params.get('exchange', 'binance')
        symbol = params.get('symbol', 'BTC/USDT')
        timeframe = params.get('timeframe', '1h')
        market_type = params.get('market_type', 'spot')
        start_date = params.get('start_date')
        end_date = params.get('end_date')
        period = params.get('period')

        # Если указан период, рассчитываем даты
        if period and not (start_date and end_date):
            from datetime import datetime, timedelta
            end_date_obj = datetime.now()

            period_days = {
                '1m': 30,
                '3m': 90,
                '6m': 180,
                '1y': 365,
                'all': None
            }

            days = period_days.get(period)
            if days:
                start_date_obj = end_date_obj - timedelta(days=days)
                start_date = start_date_obj.strftime('%Y-%m-%d')
                end_date = end_date_obj.strftime('%Y-%m-%d')
            else:
                start_date = None
                end_date = None

        task.progress = 20

        loader = DataLoader()

        # Загружаем данные
        task.progress = 30
        data = loader.load_from_api(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            exchange=exchange,
            market_type=market_type
        )

        task.progress = 80

        # Сохраняем в CSV
        filename = loader.save_to_csv()

        task.filename = filename
        task.records_count = len(data)
        task.status = 'completed'
        task.progress = 100

        print(f"[DOWNLOAD] Данные загружены: {filename}, записей: {len(data)}")

    except Exception as e:
        task.error = str(e)
        task.status = 'error'
        print(f"Ошибка при загрузке данных {task_id}: {e}")

def save_backtest_to_db(task_id, config, results):
    """Сохраняет результаты бэктеста в базу данных (PostgreSQL)"""
    try:
        # Prepare results for JSON serialization
        results_prepared = prepare_results_for_json(results) if results else None

        # Use helper function from database.py
        save_backtest_result(task_id, config, results_prepared, status='completed')

        print(f"[DB] Backtest saved: {task_id}")
    except Exception as e:
        print(f"[DB ERROR] Failed to save backtest: {e}")
        raise

def load_backtest_from_db(task_id):
    """Загружает результаты бэктеста из базы данных (PostgreSQL)"""
    try:
        backtest_dict = get_backtest_by_task_id(task_id)
        if backtest_dict and backtest_dict.get('results_json'):
            return backtest_dict['results_json']
        return None
    except Exception as e:
        print(f"[DB ERROR] Ошибка загрузки из БД: {e}")
        return None

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/config')
def config_page():
    """Страница конфигурации"""
    # Загружаем примеры конфигураций
    examples = {}

    # CSV примеры
    if os.path.isfile('config_examples.json'):
        try:
            with open('config_examples.json', 'r', encoding='utf-8') as f:
                examples['csv'] = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки config_examples.json: {e}")

    # API примеры
    if os.path.isfile('config_api_examples.json'):
        try:
            with open('config_api_examples.json', 'r', encoding='utf-8') as f:
                examples['api'] = json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки config_api_examples.json: {e}")

    # Получаем список доступных бирж
    try:
        loader = DataLoader()
        exchanges = loader.get_available_exchanges()
    except Exception as e:
        print(f"Ошибка загрузки бирж: {e}")
        exchanges = ['binance', 'okx', 'bybit', 'kucoin']  # Fallback список

    # Use helper function for CSV files
    csv_files = get_csv_files_list()

    return render_template('config.html', examples=examples, exchanges=exchanges, csv_files=csv_files)

@app.route('/api/csv-files')
def get_csv_files():
    """API для получения списка CSV файлов"""
    try:
        csv_files = []
        data_dir = Path('data')
        if data_dir.exists():
            for csv_file in data_dir.glob('*.csv'):
                file_stat = csv_file.stat()

                # Читаем первую и последнюю строку для определения диапазона дат
                date_range = None
                rows_count = 0
                try:
                    df = pd.read_csv(csv_file)
                    rows_count = len(df)
                    if 'timestamp' in df.columns and len(df) > 0:
                        start_date = pd.to_datetime(df['timestamp'].iloc[0]).strftime('%Y-%m-%d')
                        end_date = pd.to_datetime(df['timestamp'].iloc[-1]).strftime('%Y-%m-%d')
                        date_range = f"{start_date} - {end_date}"
                except Exception as e:
                    print(f"Ошибка чтения {csv_file}: {e}")

                csv_files.append({
                    'path': str(csv_file),
                    'name': csv_file.name,
                    'size': file_stat.st_size,
                    'modified': file_stat.st_mtime,
                    'date_range': date_range,
                    'rows': rows_count
                })
        # Сортируем по дате изменения (новые первыми)
        csv_files.sort(key=lambda x: x['modified'], reverse=True)
        return jsonify({'files': csv_files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/exchanges')
def get_exchanges():
    """API для получения списка бирж"""
    loader = DataLoader()
    exchanges = loader.get_available_exchanges()
    return jsonify(exchanges)

@app.route('/api/exchange-info/<exchange>')
def get_exchange_info(exchange):
    """API для получения информации о бирже"""
    loader = DataLoader()
    info = loader.get_exchange_info(exchange)
    return jsonify(info)

@app.route('/api/run-backtest', methods=['POST'])
def run_backtest():
    """API для запуска бэктеста"""
    try:
        config = request.json
        
        if not config:
            return jsonify({'error': 'Не предоставлена конфигурация'}), 400
        
        # Генерируем уникальный ID задачи
        task_id = str(uuid.uuid4())
        
        # Создаем задачу
        task = BacktestTask(task_id, config)
        running_backtests[task_id] = task
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=run_backtest_async, args=(task_id, config))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'status': 'started',
            'message': 'Бэктест запущен'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/backtest-status/<task_id>')
def get_backtest_status(task_id):
    """API для получения статуса бэктеста"""
    if task_id not in running_backtests:
        return jsonify({'error': 'Задача не найдена'}), 404
    
    task = running_backtests[task_id]
    
    response = {
        'task_id': task_id,
        'status': task.status,
        'progress': task.progress,
        'start_time': task.start_time.isoformat()
    }
    
    if task.error:
        response['error'] = task.error
    
    if task.results:
        # Добавляем основные результаты
        stats = task.results.get('basic_stats', {})
        response['results_summary'] = {
            'total_trades': stats.get('total_trades', 0),
            'win_rate': stats.get('win_rate', 0),
            'total_return': stats.get('total_return', 0),
            'final_balance': stats.get('current_balance', 0)
        }
    
    return jsonify(response)

@app.route('/api/backtest-results/<task_id>')
def get_backtest_results(task_id):
    """API для получения полных результатов бэктеста"""
    if task_id not in backtest_results:
        return jsonify({'error': 'Результаты не найдены'}), 404
    
    results = backtest_results[task_id]
    
    # Подготавливаем результаты для JSON
    json_results = prepare_results_for_json(results)
    
    return jsonify(json_results)

@app.route('/api/download-data', methods=['POST'])
def download_data():
    """API для загрузки данных с биржи (асинхронно)"""
    try:
        params = request.json

        if not params:
            return jsonify({'error': 'Не предоставлены параметры'}), 400

        # Генерируем уникальный ID задачи
        task_id = str(uuid.uuid4())

        # Создаем задачу
        task = DataDownloadTask(task_id, params)
        data_downloads[task_id] = task

        # Запускаем в отдельном потоке
        thread = threading.Thread(target=download_data_async, args=(task_id, params))
        thread.daemon = True
        thread.start()

        return jsonify({
            'task_id': task_id,
            'status': 'started',
            'message': 'Загрузка данных запущена'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/current-price', methods=['POST'])
def get_current_price():
    """Получить текущую цену с биржи"""
    try:
        params = request.json
        exchange_name = params.get('exchange', 'binance')
        symbol = params.get('symbol', 'BTC/USDT')
        market_type = params.get('market_type', 'spot')

        print(f"[PRICE API] Запрос цены: exchange={exchange_name}, symbol={symbol}, market_type={market_type}")

        # Формируем символ в зависимости от типа рынка
        full_symbol = symbol
        if market_type in ['futures', 'swap']:
            if ':' not in symbol:
                if '/USDT' in symbol:
                    full_symbol = symbol + ':USDT'

        print(f"[PRICE API] Полный символ: {full_symbol}")

        # Загружаем exchange
        import ccxt
        exchange_class = getattr(ccxt, exchange_name)
        exchange = exchange_class()

        # Загружаем рынки
        print(f"[PRICE API] Загрузка рынков с {exchange_name}...")
        exchange.load_markets()

        # Проверяем наличие символа
        if full_symbol not in exchange.markets:
            available_symbols = [s for s in exchange.markets.keys() if 'USDT' in s and symbol.split('/')[0] in s]
            error_msg = f"Символ {full_symbol} не найден на {exchange_name}."
            if available_symbols:
                error_msg += f" Возможные варианты: {', '.join(available_symbols[:5])}"
            print(f"[PRICE API ERROR] {error_msg}")
            return jsonify({'error': error_msg}), 404

        # Получаем тикер
        print(f"[PRICE API] Получение тикера для {full_symbol}...")
        ticker = exchange.fetch_ticker(full_symbol)
        current_price = ticker['last']

        print(f"[PRICE API] Успешно получена цена: {current_price}")

        return jsonify({
            'success': True,
            'price': current_price,
            'symbol': full_symbol,
            'bid': ticker.get('bid'),
            'ask': ticker.get('ask'),
            'volume': ticker.get('baseVolume'),
            'timestamp': ticker.get('timestamp')
        })

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[PRICE API ERROR] Ошибка получения цены:")
        print(error_trace)
        return jsonify({'error': str(e), 'trace': error_trace if app.debug else None}), 500

@app.route('/api/download-status/<task_id>')
def get_download_status(task_id):
    """API для получения статуса загрузки данных"""
    if task_id not in data_downloads:
        return jsonify({'error': 'Задача не найдена'}), 404

    task = data_downloads[task_id]

    response = {
        'task_id': task_id,
        'status': task.status,
        'progress': task.progress,
        'start_time': task.start_time.isoformat()
    }

    if task.error:
        response['error'] = task.error

    if task.status == 'completed':
        response['filename'] = task.filename
        response['records_count'] = task.records_count

    return jsonify(response)

@app.route('/results')
def results_page():
    """Страница результатов"""
    # Получаем список всех задач
    all_tasks = []

    # Добавляем запущенные задачи
    for task_id, task in running_backtests.items():
        all_tasks.append({
            'task_id': task_id,
            'status': task.status,
            'start_time': task.start_time,
            'config_symbol': task.config.get('symbol', 'Unknown'),
            'order_type': task.config.get('order_type', 'long'),
            'total_return': None,
            'start_date': task.config.get('start_date'),
            'end_date': task.config.get('end_date')
        })

    # Добавляем завершенные задачи из БД
    try:
        recent_backtests = get_recent_backtests(limit=50)
        for backtest in recent_backtests:
            # Проверяем, не добавили ли мы уже эту задачу из running_backtests
            if not any(t['task_id'] == backtest['task_id'] for t in all_tasks):
                all_tasks.append({
                    'task_id': backtest['task_id'],
                    'status': 'completed',
                    'start_time': backtest['created_at'],
                    'config_symbol': backtest['symbol'],
                    'total_return': backtest['total_return'],
                    'total_trades': backtest['total_trades'],
                    'order_type': backtest['order_type'],
                    'start_date': backtest['start_date'],
                    'end_date': backtest['end_date']
                })
    except Exception as e:
        print(f"[RESULTS PAGE] Ошибка загрузки из БД: {e}")

    return render_template('results.html', tasks=all_tasks)

@app.route('/results/<task_id>')
def view_results(task_id):
    """Просмотр детальных результатов"""
    # Сначала проверяем в кэше (памяти)
    if task_id in backtest_results:
        results = backtest_results[task_id]
    else:
        # Если нет в памяти, загружаем из БД
        results = load_backtest_from_db(task_id)
        if not results:
            flash('Результаты не найдены', 'error')
            return redirect(url_for('results_page'))
        # Кэшируем для быстрого доступа
        backtest_results[task_id] = results
    
    # Создаем репортер для генерации графиков
    try:
        reporter = BacktestReporter(results)
        # Генерируем графики в base64 для встраивания в HTML
        charts = generate_charts_base64(reporter)
    except Exception as e:
        print(f"Ошибка генерации графиков: {e}")
        charts = {}
    
    return render_template('view_results.html', 
                         results=results, 
                         task_id=task_id,
                         charts=charts)

@app.route('/strategies')
def strategies_page():
    """Страница управления стратегиями"""
    return render_template('strategies.html')

@app.route('/api/load-example-configs', methods=['POST'])
def load_example_configs():
    """Загружает примеры конфигураций из config_examples.json в базу данных"""
    try:
        with open('config_examples.json', 'r', encoding='utf-8') as f:
            examples = json.load(f)

        loaded_count = 0
        with get_db_session() as session:
            for name, config in examples.items():
                try:
                    # Проверяем существует ли уже
                    existing = session.query(StrategyConfig).filter_by(name=name).first()
                    if existing:
                        continue  # Пропускаем если уже есть

                    # Добавляем конфигурацию
                    new_config = StrategyConfig(
                        name=name,
                        description=f"Пример стратегии: {config.get('order_type', 'unknown')} на {config.get('symbol', 'unknown')}",
                        config_json=config,
                        is_public=True,
                        author='system'
                    )
                    session.add(new_config)
                    loaded_count += 1
                except Exception as e:
                    print(f"Ошибка загрузки примера {name}: {e}")
                    continue

        return jsonify({
            'success': True,
            'message': f'Загружено {loaded_count} примеров конфигураций',
            'loaded_count': loaded_count
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-report/<task_id>')
def generate_report(task_id):
    """Генерирует полный отчет"""
    # Сначала проверяем в кэше (памяти)
    if task_id in backtest_results:
        results = backtest_results[task_id]
    else:
        # Если нет в памяти, загружаем из БД
        results = load_backtest_from_db(task_id)
        if not results:
            return jsonify({'error': 'Результаты не найдены'}), 404
        # Кэшируем для быстрого доступа
        backtest_results[task_id] = results

    try:
        reporter = BacktestReporter(results)

        # Генерируем отчет в директории reports
        output_dir = f"reports/report_{task_id}"
        reporter.generate_full_report(output_dir)

        return jsonify({
            'success': True,
            'message': f'Отчет сгенерирован в {output_dir}',
            'report_dir': output_dir,
            'task_id': task_id
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-csv/<task_id>')
def download_csv(task_id):
    """Скачивание CSV файла со сделками"""
    try:
        # Ищем CSV файл для этого task_id
        report_dir = f"reports/report_{task_id}"
        if not os.path.exists(report_dir):
            return jsonify({'error': 'Отчет не найден. Сгенерируйте отчет сначала.'}), 404

        # Ищем CSV файл в директории
        csv_files = [f for f in os.listdir(report_dir) if f.endswith('.csv')]
        if not csv_files:
            return jsonify({'error': 'CSV файл не найден'}), 404

        csv_path = os.path.join(report_dir, csv_files[0])
        return send_file(csv_path,
                        as_attachment=True,
                        download_name=f'trades_{task_id[:8]}.csv',
                        mimetype='text/csv')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download-json/<task_id>')
def download_json(task_id):
    """Скачивание JSON файла с полными результатами"""
    try:
        # Ищем JSON файл для этого task_id
        report_dir = f"reports/report_{task_id}"
        if not os.path.exists(report_dir):
            return jsonify({'error': 'Отчет не найден. Сгенерируйте отчет сначала.'}), 404

        # Ищем JSON файл в директории
        json_files = [f for f in os.listdir(report_dir) if f.endswith('.json')]
        if not json_files:
            return jsonify({'error': 'JSON файл не найден'}), 404

        json_path = os.path.join(report_dir, json_files[0])
        return send_file(json_path,
                        as_attachment=True,
                        download_name=f'results_{task_id[:8]}.json',
                        mimetype='application/json')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/report/<task_id>')
def view_report(task_id):
    """Просмотр сгенерированного отчета с графиками"""
    report_dir = f"reports/report_{task_id}"

    if not os.path.exists(report_dir):
        flash('Отчет не найден. Сгенерируйте отчет сначала.', 'error')
        return redirect(url_for('view_results', task_id=task_id))

    # Собираем все файлы отчета
    files = {
        'images': [],
        'csv': None,
        'json': None,
        'txt': None
    }

    for filename in os.listdir(report_dir):
        filepath = os.path.join(report_dir, filename)
        if filename.endswith('.png'):
            files['images'].append({
                'name': filename,
                'path': f'/api/report-image/{task_id}/{filename}'
            })
        elif filename.endswith('.csv'):
            files['csv'] = filename
        elif filename.endswith('.json'):
            files['json'] = filename
        elif filename.endswith('.txt'):
            files['txt'] = filename
            # Читаем текстовый отчет
            with open(filepath, 'r', encoding='utf-8') as f:
                files['txt_content'] = f.read()

    return render_template('report.html', task_id=task_id, files=files)

@app.route('/api/report-image/<task_id>/<filename>')
def get_report_image(task_id, filename):
    """Отдает изображение из отчета"""
    try:
        report_dir = f"reports/report_{task_id}"
        image_path = os.path.join(report_dir, filename)

        if not os.path.exists(image_path):
            return jsonify({'error': 'Изображение не найдено'}), 404

        return send_file(image_path, mimetype='image/png')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API для работы с конфигурациями стратегий
@app.route('/api/configs')
def get_configs():
    """Получить список сохраненных конфигураций"""
    try:
        configs = get_all_strategy_configs()
        return jsonify(configs)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configs/<int:config_id>')
def get_config(config_id):
    """Получить конкретную конфигурацию"""
    try:
        with get_db_session() as session:
            config = session.query(StrategyConfig).filter_by(id=config_id).first()

            if not config:
                return jsonify({'error': 'Конфигурация не найдена'}), 404

            return jsonify(config.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configs', methods=['POST'])
def save_config():
    """Сохранить новую конфигурацию"""
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        config = data.get('config')
        is_public = data.get('is_public', False)
        author = data.get('author', 'user')
        tags = data.get('tags', [])

        if not name:
            return jsonify({'error': 'Название конфигурации обязательно'}), 400

        with get_db_session() as session:
            # Check if name already exists
            existing = session.query(StrategyConfig).filter_by(name=name).first()
            if existing:
                return jsonify({'error': 'Конфигурация с таким именем уже существует'}), 400

            new_config = StrategyConfig(
                name=name,
                description=description,
                config_json=config,
                is_public=is_public,
                author=author,
                tags=tags if isinstance(tags, list) else []
            )
            session.add(new_config)
            session.flush()  # To get the ID

            return jsonify({
                'success': True,
                'message': f'Конфигурация "{name}" сохранена',
                'id': new_config.id
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configs/<int:config_id>', methods=['PUT'])
def update_config(config_id):
    """Обновить существующую конфигурацию"""
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        config = data.get('config')
        is_public = data.get('is_public', False)
        tags = data.get('tags', [])

        with get_db_session() as session:
            existing_config = session.query(StrategyConfig).filter_by(id=config_id).first()

            if not existing_config:
                return jsonify({'error': 'Конфигурация не найдена'}), 404

            existing_config.name = name
            existing_config.description = description
            existing_config.config_json = config
            existing_config.is_public = is_public
            existing_config.tags = tags if isinstance(tags, list) else []
            existing_config.updated_at = datetime.utcnow()

            return jsonify({'success': True, 'message': 'Конфигурация обновлена'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configs/<int:config_id>', methods=['DELETE'])
def delete_config(config_id):
    """Удалить конфигурацию"""
    try:
        with get_db_session() as session:
            config = session.query(StrategyConfig).filter_by(id=config_id).first()

            if not config:
                return jsonify({'error': 'Конфигурация не найдена'}), 404

            session.delete(config)
            return jsonify({'success': True, 'message': 'Конфигурация удалена'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/configs/<int:config_id>/duplicate', methods=['POST'])
def duplicate_config(config_id):
    """Дублировать конфигурацию"""
    try:
        with get_db_session() as session:
            original = session.query(StrategyConfig).filter_by(id=config_id).first()

            if not original:
                return jsonify({'error': 'Конфигурация не найдена'}), 404

            # Создаем копию с новым именем
            new_name = f"{original.name} (копия)"
            new_config = StrategyConfig(
                name=new_name,
                description=original.description,
                config_json=original.config_json,
                is_public=False,
                author=original.author,
                tags=original.tags
            )
            session.add(new_config)
            session.flush()  # To get the ID

            return jsonify({
                'success': True,
                'message': f'Конфигурация скопирована как "{new_name}"',
                'id': new_config.id
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def prepare_results_for_json(results):
    """Подготавливает результаты для JSON сериализации"""
    import math

    def convert_for_json(obj):
        if hasattr(obj, 'isoformat'):  # datetime
            return obj.isoformat()
        elif hasattr(obj, 'item'):  # numpy types
            value = obj.item()
            # Проверяем на Infinity/NaN после извлечения из numpy
            if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
                return None
            return value
        elif isinstance(obj, float):
            # Заменяем Infinity и NaN на null для корректной JSON сериализации
            if math.isinf(obj) or math.isnan(obj):
                return None
            return obj
        elif isinstance(obj, dict):
            return {key: convert_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [convert_for_json(item) for item in obj]
        elif hasattr(obj, '__dict__'):  # Объекты классов (Trade, etc)
            return convert_for_json(obj.__dict__)
        else:
            return obj

    return convert_for_json(results)

def generate_charts_base64(reporter):
    """Генерирует графики в формате base64"""
    charts = {}
    
    try:
        import matplotlib
        matplotlib.use('Agg')  # Используем backend без GUI
        import matplotlib.pyplot as plt
        
        # График эквити
        if reporter.balance_history:
            plt.figure(figsize=(10, 6))
            reporter.create_equity_curve_plot(show=False)
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', bbox_inches='tight')
            img_buffer.seek(0)
            
            charts['equity_curve'] = base64.b64encode(img_buffer.getvalue()).decode()
            plt.close()
        
        # График распределения PnL
        if reporter.trade_history:
            plt.figure(figsize=(10, 6))
            reporter.create_pnl_distribution_plot(show=False)
            
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', bbox_inches='tight')
            img_buffer.seek(0)
            
            charts['pnl_distribution'] = base64.b64encode(img_buffer.getvalue()).decode()
            plt.close()
            
    except Exception as e:
        print(f"Ошибка генерации графиков: {e}")
    
    return charts

@app.route('/api/backtest/<task_id>', methods=['DELETE'])
def delete_backtest(task_id):
    """Удаляет бэктест из базы данных и файлы отчетов"""
    try:
        import shutil

        # Удаляем из памяти
        if task_id in running_backtests:
            del running_backtests[task_id]
        if task_id in backtest_results:
            del backtest_results[task_id]

        # Удаляем из базы данных
        deleted_count = 0
        with get_db_session() as session:
            backtest = session.query(BacktestHistory).filter_by(task_id=task_id).first()
            if backtest:
                session.delete(backtest)
                deleted_count = 1

        # Удаляем директорию с отчетами
        report_dir = f"reports/report_{task_id}"
        if os.path.exists(report_dir):
            shutil.rmtree(report_dir)
            print(f"[DELETE] Удалена директория отчета: {report_dir}")

        if deleted_count > 0:
            return jsonify({
                'success': True,
                'message': 'Бэктест успешно удален'
            })
        else:
            return jsonify({'error': 'Бэктест не найден'}), 404

    except Exception as e:
        print(f"[DELETE ERROR] Ошибка удаления бэктеста: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/backtest/clear-all', methods=['DELETE'])
def clear_all_backtests():
    """Удаляет все завершенные бэктесты"""
    try:
        import shutil

        # Получаем список всех task_id из базы
        with get_db_session() as session:
            backtests = session.query(BacktestHistory).filter_by(status='completed').all()
            task_ids = [b.task_id for b in backtests]

            # Удаляем все записи
            for backtest in backtests:
                session.delete(backtest)

            deleted_count = len(backtests)

        # Очищаем память
        for task_id in task_ids:
            if task_id in running_backtests:
                del running_backtests[task_id]
            if task_id in backtest_results:
                del backtest_results[task_id]

            # Удаляем директории с отчетами
            report_dir = f"reports/report_{task_id}"
            if os.path.exists(report_dir):
                shutil.rmtree(report_dir)

        print(f"[DELETE] Удалено {deleted_count} бэктестов")

        return jsonify({
            'success': True,
            'message': f'Удалено {deleted_count} бэктестов',
            'deleted_count': deleted_count
        })

    except Exception as e:
        print(f"[DELETE ERROR] Ошибка очистки бэктестов: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/visualization/<task_id>')
def get_visualization(task_id):
    """API для получения plotly визуализации"""
    try:
        # Получаем результаты
        if task_id in backtest_results:
            results = backtest_results[task_id]
        else:
            results = load_backtest_from_db(task_id)
            if not results:
                return jsonify({'error': 'Результаты не найдены'}), 404
            backtest_results[task_id] = results

        # Получаем OHLCV данные если есть
        data = None

        # ПРИОРИТЕТ 1: Используем сохраненные данные из результатов
        if 'ohlcv_data' in results and results['ohlcv_data']:
            try:
                data = pd.DataFrame(results['ohlcv_data'])
                # Конвертируем timestamp обратно в datetime
                data['timestamp'] = pd.to_datetime(data['timestamp'])
                print(f"[DEBUG VISUALIZATION] Загружено {len(data)} свечей из ohlcv_data")
            except Exception as e:
                print(f"Ошибка конвертации ohlcv_data в DataFrame: {e}")

        # ПРИОРИТЕТ 2: Fallback - загружаем из файла если данных нет
        if data is None and 'data_summary' in results and results['data_summary']:
            config = results.get('config', {})
            data_source = config.get('data_source', {})
            source_type = data_source.get('type', 'csv')

            print(f"[DEBUG VISUALIZATION] Загрузка данных из файла, source_type={source_type}")

            if source_type == 'csv':
                # Single timeframe CSV
                file_path = data_source.get('file')
                if file_path and os.path.exists(file_path):
                    try:
                        loader = DataLoader()
                        data = loader.load_from_csv(file_path, config.get('symbol'))
                    except Exception as e:
                        print(f"Ошибка загрузки CSV данных: {e}")

            elif source_type == 'csv_dual':
                # Dual timeframe CSV - загружаем EXECUTION файл (низкий таймфрейм)
                execution_file = data_source.get('execution_file')
                if execution_file and os.path.exists(execution_file):
                    try:
                        loader = DataLoader()
                        data = loader.load_from_csv(execution_file, config.get('symbol'))
                        print(f"[DEBUG VISUALIZATION] Загружен execution CSV: {execution_file}")
                    except Exception as e:
                        print(f"Ошибка загрузки dual CSV данных: {e}")
                else:
                    print(f"[WARNING] Execution CSV файл не найден: {execution_file}")

            elif source_type == 'api':
                # API источник - данные должны быть в ohlcv_data
                print(f"[WARNING] API источник без ohlcv_data - данные недоступны для визуализации")

        if data is None:
            print(f"[ERROR VISUALIZATION] Данные не загружены. ohlcv_data: {bool(results.get('ohlcv_data'))}, data_summary: {bool(results.get('data_summary'))}")

        # Создаем визуализатор
        viz = BacktestVisualizer(results, data)

        # Получаем тип графика из параметров
        chart_type = request.args.get('type', 'all')
        show_ema = request.args.get('show_ema', 'false').lower() == 'true'
        show_rsi = request.args.get('show_rsi', 'false').lower() == 'true'

        print(f"[DEBUG VISUALIZATION] task_id={task_id}, chart_type={chart_type}, show_ema={show_ema}, show_rsi={show_rsi}")

        # Создаем график
        if chart_type == 'all':
            fig = viz.plot_all()
        elif chart_type == 'price':
            fig = viz.plot_price_and_trades(show_ema=show_ema, show_rsi=show_rsi)
        elif chart_type == 'balance':
            fig = viz.plot_balance()
        elif chart_type == 'pnl':
            fig = viz.plot_pnl()
        elif chart_type == 'drawdown':
            fig = viz.plot_drawdown()
        elif chart_type == 'distribution':
            fig = viz.plot_trade_distribution()
        else:
            return jsonify({'error': f'Неизвестный тип графика: {chart_type}'}), 400

        # Логируем информацию о графике
        print(f"[DEBUG VISUALIZATION] Создан график с {len(fig.data)} traces")
        for i, trace in enumerate(fig.data):
            trace_name = getattr(trace, 'name', 'unnamed')
            print(f"  Trace {i}: {trace_name} (type: {type(trace).__name__})")

        # Вместо HTML возвращаем JSON с данными для Plotly
        graph_json = fig.to_json()

        print(f"[DEBUG VISUALIZATION] JSON serialization complete")

        # Получаем периоды EMA для отображения в UI
        ema_short, ema_long = viz.get_ema_periods()

        return jsonify({
            'success': True,
            'graph_json': graph_json,
            'task_id': task_id,
            'chart_type': chart_type,
            'ema_periods': [ema_short, ema_long]
        })

    except Exception as e:
        import traceback
        print(f"Ошибка визуализации: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/visualization/<task_id>')
def visualization_page(task_id):
    """Страница с интерактивной визуализацией"""
    # Проверяем существование результатов
    if task_id not in backtest_results:
        results = load_backtest_from_db(task_id)
        if not results:
            flash('Результаты не найдены', 'error')
            return redirect(url_for('results_page'))
        backtest_results[task_id] = results

    return render_template('visualization.html', task_id=task_id)

@app.route('/test-plotly')
def test_plotly():
    """Тестовая страница Plotly"""
    return render_template('test_plotly.html')

@app.route('/health')
def health_check():
    """Health check endpoint for container orchestration"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0'
    }), 200

# ============================================================================
# Optimization Routes (Protected - Admin Only)
# ============================================================================

def require_optimizer_access(f):
    """Decorator to check optimizer access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get user_id from request
        user_id = request.headers.get('X-User-ID') or request.args.get('user_id')

        if not user_id:
            return jsonify({
                'error': 'Unauthorized - user_id required',
                'hint': 'Add X-User-ID header or ?user_id= parameter'
            }), 401

        # Check access
        if not check_user_optimizer_access(str(user_id)):
            return jsonify({
                'error': 'Forbidden - optimizer access denied',
                'user_id': user_id,
                'hint': 'Contact admin to grant optimizer access'
            }), 403

        return f(*args, **kwargs)
    return decorated_function


@app.route('/optimize')
def optimize_page():
    """Optimization configuration page (protected)"""
    # Use helper function for CSV files
    csv_files = get_csv_files_list()
    return render_template('optimize.html', csv_files=csv_files)


@app.route('/optimization-results/<task_id>')
def optimization_results_page(task_id):
    """Optimization results page"""
    return render_template('optimization_results.html', task_id=task_id)


@app.route('/api/optimize/start', methods=['POST'])
@require_optimizer_access
def start_optimization():
    """Start optimization task"""
    try:
        data = request.json

        if not data:
            return jsonify({'error': 'No configuration provided'}), 400

        base_config = data.get('base_config')
        optimization_params = data.get('optimization_params')
        n_trials = data.get('n_trials', 100)
        user_id = request.headers.get('X-User-ID') or request.args.get('user_id')

        if not base_config or not optimization_params:
            return jsonify({'error': 'base_config and optimization_params required'}), 400

        # Import notification function
        try:
            import sys
            sys.path.append('market-analytics/bot')
            from notifications import send_optimization_notification
            notification_callback = send_optimization_notification
        except Exception as e:
            print(f"Warning: Could not import notification function: {e}")
            notification_callback = None

        # Add task to queue
        task_id = global_optimization_queue.add_task(
            config=base_config,
            optimization_params=optimization_params,
            n_trials=n_trials,
            user_id=user_id,
            notification_callback=notification_callback
        )

        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Optimization task added to queue',
            'queue_position': len(global_optimization_queue.queue)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/status/<task_id>')
def get_optimization_status(task_id):
    """Get optimization task status"""
    try:
        status = global_optimization_queue.get_task_status(task_id)

        if not status:
            # Check database
            db_result = get_optimization_by_task_id(task_id)
            if db_result:
                return jsonify(db_result)
            return jsonify({'error': 'Task not found'}), 404

        return jsonify(status)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/queue')
def get_optimization_queue_status():
    """Get overall queue status"""
    try:
        status = global_optimization_queue.get_queue_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/results/<task_id>')
def get_optimization_results(task_id):
    """Get optimization results"""
    try:
        # Check queue first
        status = global_optimization_queue.get_task_status(task_id)

        if status and status.get('results'):
            return jsonify(status['results'])

        # Check database
        db_result = get_optimization_by_task_id(task_id)
        if db_result:
            return jsonify(db_result)

        return jsonify({'error': 'Results not found'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/history')
def get_optimization_history():
    """Get recent optimization history"""
    try:
        limit = request.args.get('limit', 20, type=int)
        history = get_recent_optimizations(limit=limit)
        return jsonify(history)
    except Exception as e:
        logger.error(f"Failed to fetch optimization history: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/cancel/<task_id>', methods=['POST'])
@require_optimizer_access
def cancel_optimization(task_id):
    """Cancel pending optimization task"""
    try:
        success = global_optimization_queue.cancel_task(task_id)

        if success:
            return jsonify({'success': True, 'message': 'Task cancelled'})
        else:
            return jsonify({'error': 'Task not found or already running'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/optimize/save-config/<task_id>', methods=['POST'])
@require_optimizer_access
def save_optimized_config(task_id):
    """Save best configuration from optimization as strategy config"""
    try:
        # Get optimization results
        optimization = get_optimization_by_task_id(task_id)

        if not optimization:
            return jsonify({'error': 'Optimization not found'}), 404

        best_config = optimization.get('best_config')
        if not best_config:
            return jsonify({'error': 'No best config found'}), 404

        # Generate name
        symbol = best_config.get('symbol', 'UNKNOWN')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        config_name = f"Optimized_{symbol}_{timestamp}"

        # Save as strategy config
        save_strategy_config(
            name=config_name,
            config=best_config,
            description=f"Auto-generated from optimization {task_id[:8]}",
            tags=['optimized', 'auto-generated']
        )

        return jsonify({
            'success': True,
            'message': f'Configuration saved as "{config_name}"'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Страница не найдена'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

if __name__ == '__main__':
    # Создаем необходимые директории
    os.makedirs('data', exist_ok=True)
    os.makedirs('reports', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Инициализируем базу данных
    init_database()
    
    app.run(host='0.0.0.0', port=8000, debug=True) 