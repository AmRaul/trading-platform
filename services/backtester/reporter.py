import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import json
from datetime import datetime

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Matplotlib не установлен. Графики недоступны.")

class BacktestReporter:
    """
    Класс для создания отчетов по результатам бэктестирования
    """
    
    def __init__(self, results: dict):
        """
        Инициализация репортера
        
        Args:
            results: результаты бэктеста из класса Backtester
        """
        self.results = results
        self.basic_stats = results.get('basic_stats', {})
        self.advanced_metrics = results.get('advanced_metrics', {})
        self.trade_history = results.get('trade_history', [])
        self.balance_history = results.get('balance_history', [])
        self.config = results.get('config', {})
    
    def generate_summary_report(self) -> str:
        """
        Генерирует текстовый отчет-сводку
        
        Returns:
            Строка с отчетом
        """
        report = []
        report.append("=" * 60)
        report.append("ОТЧЕТ ПО БЭКТЕСТИРОВАНИЮ")
        report.append("=" * 60)
        
        # Основная информация
        report.append(f"\n📋 КОНФИГУРАЦИЯ:")
        report.append(f"Символ: {self.config.get('symbol', 'N/A')}")
        report.append(f"Таймфрейм: {self.config.get('timeframe', 'N/A')}")
        report.append(f"Начальный баланс: ${self.config.get('start_balance', 0):,.2f}")
        report.append(f"Тип ордеров: {self.config.get('order_type', 'N/A').upper()}")
        
        # DCA настройки
        dca_config = self.config.get('dca', {})
        if dca_config.get('enabled', False):
            report.append(f"\n🔄 DCA НАСТРОЙКИ:")
            report.append(f"Максимум ордеров: {dca_config.get('max_orders', 'N/A')}")
            report.append(f"Шаг DCA: {dca_config.get('step_percent', 'N/A')}%")
            report.append(f"Мультипликатор: {dca_config.get('multiplier', 'N/A')}x")
        
        # Основные результаты
        report.append(f"\n💰 ФИНАНСОВЫЕ РЕЗУЛЬТАТЫ:")
        report.append(f"Финальный баланс: ${self.basic_stats.get('current_balance', 0):,.2f}")
        report.append(f"Общая прибыль/убыток: ${self.basic_stats.get('total_pnl', 0):,.2f}")
        report.append(f"Доходность: {self.basic_stats.get('total_return', 0):.2f}%")
        report.append(f"Максимальная просадка: {self.advanced_metrics.get('max_drawdown_percent', 0):.2f}%")
        
        # Статистика сделок
        report.append(f"\n📊 СТАТИСТИКА СДЕЛОК:")
        report.append(f"Всего сделок: {self.basic_stats.get('total_trades', 0)}")
        report.append(f"Прибыльных: {self.basic_stats.get('winning_trades', 0)} ({self.basic_stats.get('win_rate', 0):.1f}%)")
        report.append(f"Убыточных: {self.basic_stats.get('losing_trades', 0)}")
        
        if self.basic_stats.get('total_trades', 0) > 0:
            report.append(f"Средняя сделка: ${self.basic_stats.get('average_pnl', 0):.2f}")
            report.append(f"Лучшая сделка: ${self.basic_stats.get('max_profit', 0):.2f}")
            report.append(f"Худшая сделка: ${self.basic_stats.get('max_loss', 0):.2f}")
        
        # Дополнительные метрики
        report.append(f"\n📈 ДОПОЛНИТЕЛЬНЫЕ МЕТРИКИ:")
        report.append(f"Profit Factor: {self.advanced_metrics.get('profit_factor', 0):.2f}")
        report.append(f"Sharpe Ratio: {self.advanced_metrics.get('sharpe_ratio', 0):.2f}")
        report.append(f"Средняя длительность сделки: {self.advanced_metrics.get('avg_trade_duration_hours', 0):.1f} часов")
        report.append(f"Максимум побед подряд: {self.advanced_metrics.get('max_consecutive_wins', 0)}")
        report.append(f"Максимум поражений подряд: {self.advanced_metrics.get('max_consecutive_losses', 0)}")
        
        report.append("\n" + "=" * 60)
        
        return "\n".join(report)
    
    def generate_trades_report(self) -> pd.DataFrame:
        """
        Генерирует детальный отчет по сделкам
        
        Returns:
            DataFrame с информацией о сделках
        """
        if not self.trade_history:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.trade_history)
        
        # Добавляем дополнительные колонки для анализа
        df['duration_hours'] = pd.to_datetime(df['exit_time']) - pd.to_datetime(df['entry_time'])
        df['duration_hours'] = df['duration_hours'].dt.total_seconds() / 3600
        
        df['profit_loss'] = df['pnl'].apply(lambda x: 'Profit' if x > 0 else 'Loss')
        df['cumulative_pnl'] = df['pnl'].cumsum()
        df['trade_number'] = range(1, len(df) + 1)
        
        # Форматируем колонки для лучшего отображения
        numeric_columns = ['entry_price', 'exit_price', 'quantity', 'pnl', 'pnl_percent']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = df[col].round(4)
        
        return df
    
    def analyze_performance_by_time(self) -> Dict:
        """
        Анализирует производительность по времени
        
        Returns:
            Словарь с анализом по временным периодам
        """
        if not self.trade_history:
            return {}
        
        df = pd.DataFrame(self.trade_history)
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['hour'] = df['exit_time'].dt.hour
        df['day_of_week'] = df['exit_time'].dt.day_name()
        df['month'] = df['exit_time'].dt.month_name()
        
        analysis = {}
        
        # Анализ по часам
        hourly_stats = df.groupby('hour').agg({
            'pnl': ['count', 'sum', 'mean'],
            'pnl_percent': 'mean'
        }).round(2)
        analysis['hourly'] = hourly_stats.to_dict()
        
        # Анализ по дням недели
        daily_stats = df.groupby('day_of_week').agg({
            'pnl': ['count', 'sum', 'mean'],
            'pnl_percent': 'mean'
        }).round(2)
        analysis['daily'] = daily_stats.to_dict()
        
        # Анализ по месяцам
        monthly_stats = df.groupby('month').agg({
            'pnl': ['count', 'sum', 'mean'],
            'pnl_percent': 'mean'
        }).round(2)
        analysis['monthly'] = monthly_stats.to_dict()
        
        return analysis
    
    def create_equity_curve_plot(self, save_path: str = None, show: bool = True):
        """
        Создает график кривой эквити (изменения баланса)
        
        Args:
            save_path: путь для сохранения графика
            show: показывать ли график
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib не установлен. График недоступен.")
            return
        
        if not self.balance_history:
            print("Нет данных для построения графика баланса.")
            return
        
        # Подготавливаем данные
        timestamps = [pd.to_datetime(entry['timestamp']) for entry in self.balance_history]
        balances = [entry['balance'] for entry in self.balance_history]
        
        # Добавляем начальную точку
        timestamps.insert(0, timestamps[0])  # Используем первую дату
        balances.insert(0, self.config.get('start_balance', 1000))
        
        plt.figure(figsize=(12, 6))
        plt.plot(timestamps, balances, linewidth=2, color='blue', label='Баланс')
        
        # Добавляем горизонтальную линию начального баланса
        plt.axhline(y=self.config.get('start_balance', 1000), 
                   color='red', linestyle='--', alpha=0.7, label='Начальный баланс')
        
        plt.title('Кривая эквити (изменение баланса)', fontsize=14, fontweight='bold')
        plt.xlabel('Время')
        plt.ylabel('Баланс ($)')
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        # Форматируем оси
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(timestamps)//10)))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"График сохранен: {save_path}")
        
        if show:
            plt.show()
    
    def create_pnl_distribution_plot(self, save_path: str = None, show: bool = True):
        """
        Создает график распределения прибылей/убытков
        
        Args:
            save_path: путь для сохранения графика
            show: показывать ли график
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib не установлен. График недоступен.")
            return
        
        if not self.trade_history:
            print("Нет данных о сделках для построения графика.")
            return
        
        pnl_values = [trade['pnl'] for trade in self.trade_history]
        
        plt.figure(figsize=(10, 6))
        
        # Гистограмма
        plt.hist(pnl_values, bins=20, alpha=0.7, color='skyblue', edgecolor='black')
        
        # Вертикальные линии для статистики
        plt.axvline(x=0, color='red', linestyle='-', alpha=0.8, label='Безубыток')
        plt.axvline(x=np.mean(pnl_values), color='green', linestyle='--', 
                   alpha=0.8, label=f'Среднее: ${np.mean(pnl_values):.2f}')
        
        plt.title('Распределение прибылей и убытков', fontsize=14, fontweight='bold')
        plt.xlabel('Прибыль/Убыток ($)')
        plt.ylabel('Количество сделок')
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"График сохранен: {save_path}")
        
        if show:
            plt.show()
    
    def create_drawdown_plot(self, save_path: str = None, show: bool = True):
        """
        Создает график просадки
        
        Args:
            save_path: путь для сохранения графика
            show: показывать ли график
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib не установлен. График недоступен.")
            return
        
        if not self.balance_history:
            print("Нет данных для построения графика просадки.")
            return
        
        # Вычисляем просадку
        balances = [self.config.get('start_balance', 1000)] + [entry['balance'] for entry in self.balance_history]
        timestamps = [pd.to_datetime(self.balance_history[0]['timestamp'])] + \
                    [pd.to_datetime(entry['timestamp']) for entry in self.balance_history]
        
        # Вычисляем максимальный баланс на каждый момент времени
        max_balance = []
        current_max = balances[0]
        
        for balance in balances:
            if balance > current_max:
                current_max = balance
            max_balance.append(current_max)
        
        # Вычисляем просадку в процентах
        drawdown = [(max_bal - bal) / max_bal * 100 for max_bal, bal in zip(max_balance, balances)]
        
        plt.figure(figsize=(12, 6))
        plt.fill_between(timestamps, drawdown, 0, alpha=0.3, color='red', label='Просадка')
        plt.plot(timestamps, drawdown, color='red', linewidth=1)
        
        plt.title('График просадки портфеля', fontsize=14, fontweight='bold')
        plt.xlabel('Время')
        plt.ylabel('Просадка (%)')
        plt.grid(True, alpha=0.3)
        plt.legend()
        
        # Инвертируем ось Y для лучшего восприятия
        plt.gca().invert_yaxis()
        
        # Форматируем оси
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(timestamps)//10)))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"График сохранен: {save_path}")
        
        if show:
            plt.show()
    
    def create_monthly_returns_plot(self, save_path: str = None, show: bool = True):
        """
        Создает график месячной доходности
        
        Args:
            save_path: путь для сохранения графика
            show: показывать ли график
        """
        if not MATPLOTLIB_AVAILABLE:
            print("Matplotlib не установлен. График недоступен.")
            return
        
        if not self.trade_history:
            print("Нет данных о сделках для построения графика.")
            return
        
        df = pd.DataFrame(self.trade_history)
        df['exit_time'] = pd.to_datetime(df['exit_time'])
        df['year_month'] = df['exit_time'].dt.to_period('M')
        
        monthly_pnl = df.groupby('year_month')['pnl'].sum()
        
        plt.figure(figsize=(12, 6))
        colors = ['green' if x >= 0 else 'red' for x in monthly_pnl.values]
        bars = plt.bar(range(len(monthly_pnl)), monthly_pnl.values, color=colors, alpha=0.7)
        
        plt.title('Месячная доходность', fontsize=14, fontweight='bold')
        plt.xlabel('Месяц')
        plt.ylabel('Прибыль/Убыток ($)')
        plt.grid(True, alpha=0.3, axis='y')
        
        # Настраиваем подписи оси X
        plt.xticks(range(len(monthly_pnl)), 
                  [str(period) for period in monthly_pnl.index], 
                  rotation=45)
        
        # Добавляем значения на столбцы
        for i, bar in enumerate(bars):
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height,
                    f'${height:.0f}',
                    ha='center', va='bottom' if height >= 0 else 'top')
        
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"График сохранен: {save_path}")
        
        if show:
            plt.show()
    
    def generate_full_report(self, output_dir: str = "results"):
        """
        Генерирует полный отчет со всеми графиками
        
        Args:
            output_dir: директория для сохранения отчетов
        """
        import os
        
        # Создаем директорию если не существует
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Сохраняем текстовый отчет
        summary = self.generate_summary_report()
        with open(f"{output_dir}/summary_report_{timestamp}.txt", 'w', encoding='utf-8') as f:
            f.write(summary)
        
        # Сохраняем детальный отчет по сделкам
        trades_df = self.generate_trades_report()
        if not trades_df.empty:
            trades_df.to_csv(f"{output_dir}/trades_report_{timestamp}.csv", index=False)
        
        # Создаем графики если matplotlib доступен
        if MATPLOTLIB_AVAILABLE:
            self.create_equity_curve_plot(
                save_path=f"{output_dir}/equity_curve_{timestamp}.png", 
                show=False
            )
            self.create_pnl_distribution_plot(
                save_path=f"{output_dir}/pnl_distribution_{timestamp}.png", 
                show=False
            )
            self.create_drawdown_plot(
                save_path=f"{output_dir}/drawdown_{timestamp}.png", 
                show=False
            )
            self.create_monthly_returns_plot(
                save_path=f"{output_dir}/monthly_returns_{timestamp}.png", 
                show=False
            )
        
        # Сохраняем полные результаты в JSON
        with open(f"{output_dir}/full_results_{timestamp}.json", 'w', encoding='utf-8') as f:
            json.dump(self._prepare_for_json(self.results), f, indent=2, ensure_ascii=False)
        
        print(f"\nПолный отчет сохранен в директории: {output_dir}")
        print(f"Файлы:")
        print(f"  - summary_report_{timestamp}.txt")
        print(f"  - trades_report_{timestamp}.csv")
        print(f"  - full_results_{timestamp}.json")
        if MATPLOTLIB_AVAILABLE:
            print(f"  - equity_curve_{timestamp}.png")
            print(f"  - pnl_distribution_{timestamp}.png")
            print(f"  - drawdown_{timestamp}.png")
            print(f"  - monthly_returns_{timestamp}.png")
    
    def _prepare_for_json(self, obj):
        """Подготавливает объект для сериализации в JSON"""
        if isinstance(obj, dict):
            return {key: self._prepare_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._prepare_for_json(item) for item in obj]
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif pd.isna(obj):
            return None
        else:
            return obj
    
    def print_top_trades(self, n: int = 10):
        """
        Выводит топ лучших и худших сделок
        
        Args:
            n: количество сделок для показа
        """
        if not self.trade_history:
            print("Нет данных о сделках.")
            return
        
        # Исключаем сделки с "end_of_data" из топ сделок
        completed_trades = [t for t in self.trade_history if t['reason'] != 'end_of_data']
        
        if not completed_trades:
            print("Нет завершенных сделок для анализа.")
            return
        
        df = pd.DataFrame(completed_trades)
        
        print(f"\n🏆 ТОП {n} ЛУЧШИХ СДЕЛОК:")
        print("-" * 60)
        best_trades = df.nlargest(n, 'pnl')
        for i, (_, trade) in enumerate(best_trades.iterrows(), 1):
            exit_time_str = str(trade['exit_time'])[:19] if hasattr(trade['exit_time'], '__getitem__') else str(trade['exit_time'])
            print(f"{i:2d}. {exit_time_str} | "
                  f"${trade['pnl']:8.2f} ({trade['pnl_percent']:6.2f}%) | "
                  f"{trade['entry_price']:.4f} → {trade['exit_price']:.4f}")
        
        print(f"\n💥 ТОП {n} ХУДШИХ СДЕЛОК:")
        print("-" * 60)
        worst_trades = df.nsmallest(n, 'pnl')
        for i, (_, trade) in enumerate(worst_trades.iterrows(), 1):
            exit_time_str = str(trade['exit_time'])[:19] if hasattr(trade['exit_time'], '__getitem__') else str(trade['exit_time'])
            print(f"{i:2d}. {exit_time_str} | "
                  f"${trade['pnl']:8.2f} ({trade['pnl_percent']:6.2f}%) | "
                  f"{trade['entry_price']:.4f} → {trade['exit_price']:.4f}")
    
    def get_risk_metrics(self) -> Dict:
        """
        Вычисляет дополнительные метрики риска
        
        Returns:
            Словарь с метриками риска
        """
        if not self.trade_history:
            return {}
        
        # Исключаем сделки с "end_of_data" из расчета метрик риска
        completed_trades = [t for t in self.trade_history if t['reason'] != 'end_of_data']
        
        if not completed_trades:
            return {}
        
        df = pd.DataFrame(completed_trades)
        returns = df['pnl_percent'] / 100  # Конвертируем в доли
        
        risk_metrics = {
            'volatility': returns.std() * np.sqrt(252),  # Годовая волатильность
            'var_95': np.percentile(returns, 5),  # VaR 95%
            'var_99': np.percentile(returns, 1),  # VaR 99%
            'skewness': returns.skew(),  # Асимметрия
            'kurtosis': returns.kurtosis(),  # Эксцесс
            'calmar_ratio': self.basic_stats.get('total_return', 0) / max(self.advanced_metrics.get('max_drawdown_percent', 1), 1),
            'recovery_factor': abs(self.basic_stats.get('total_pnl', 0)) / max(abs(self.basic_stats.get('max_loss', 1)), 1)
        }
        
        return risk_metrics 