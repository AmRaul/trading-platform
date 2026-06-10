"""
Strategy Optimization Module using Optuna
Bayesian optimization for finding optimal strategy parameters
"""

import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable, Tuple
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import copy

from backtester import Backtester
from reporter import BacktestReporter

logger = logging.getLogger(__name__)


class OptunaOptimizer:
    """
    Bayesian optimization for trading strategy parameters using Optuna
    """

    def __init__(
        self,
        base_config: dict,
        optimization_params: dict,
        n_trials: int = 100,
        max_parallel_backtests: int = 4,
        optimization_metric: str = 'custom_score',
        notification_callback: Optional[Callable] = None,
        user_id: Optional[str] = None
    ):
        """
        Initialize optimizer

        Args:
            base_config: Base strategy configuration
            optimization_params: Dict with parameter ranges to optimize
                Example: {
                    'take_profit.target_percent': [1.0, 2.0, 3.0, 5.0],
                    'dca.max_orders': [3, 5, 7, 10],
                    'entry_conditions.rsi_oversold': [20, 30, 40]
                }
            n_trials: Number of optimization trials
            max_parallel_backtests: Max parallel backtest executions
            optimization_metric: Metric to optimize ('custom_score', 'sharpe_ratio', 'profit_factor', 'total_return')
            notification_callback: Function to send notifications (Telegram)
            user_id: User ID for notifications
        """
        self.base_config = base_config
        self.optimization_params = optimization_params
        self.n_trials = n_trials
        self.max_parallel_backtests = max_parallel_backtests
        self.optimization_metric = optimization_metric
        self.notification_callback = notification_callback
        self.user_id = user_id

        # Results tracking
        self.all_results = []
        self.best_params = None
        self.best_score = float('-inf')
        self.trial_count = 0

        # Walk-forward periods
        self.train_split = 0.6
        self.validation_split = 0.2
        self.test_split = 0.2

    def _set_nested_value(self, config: dict, key_path: str, value):
        """
        Set nested dictionary value using dot notation

        Example: 'take_profit.target_percent' -> config['take_profit']['target_percent'] = value
        """
        keys = key_path.split('.')
        current = config

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def _get_nested_value(self, config: dict, key_path: str):
        """Get nested dictionary value using dot notation"""
        keys = key_path.split('.')
        current = config

        for key in keys:
            current = current.get(key, {})

        return current

    def _create_config_from_params(self, params: dict) -> dict:
        """
        Create configuration from parameter dictionary (NOT from trial)
        Use this for recreating best config after optimization completes

        Args:
            params: Dictionary of parameter values (e.g., from best_trial.params)

        Returns:
            Complete strategy configuration
        """
        config = copy.deepcopy(self.base_config)

        for param_path, value in params.items():
            self._set_nested_value(config, param_path, value)

        return config

    def _create_config_from_trial(self, trial: optuna.Trial) -> dict:
        """
        Create configuration from Optuna trial suggestions

        Args:
            trial: Optuna trial object

        Returns:
            Complete strategy configuration
        """
        config = copy.deepcopy(self.base_config)

        for param_path, values in self.optimization_params.items():
            if isinstance(values, list):
                # Categorical choice
                if all(isinstance(v, int) for v in values):
                    suggested_value = trial.suggest_int(param_path, min(values), max(values))
                elif all(isinstance(v, float) for v in values):
                    suggested_value = trial.suggest_float(param_path, min(values), max(values))
                else:
                    suggested_value = trial.suggest_categorical(param_path, values)
            elif isinstance(values, dict):
                # Range specification: {'min': 1.0, 'max': 5.0, 'step': 0.5}
                if 'step' in values:
                    suggested_value = trial.suggest_float(
                        param_path,
                        values['min'],
                        values['max'],
                        step=values['step']
                    )
                else:
                    if isinstance(values['min'], int) and isinstance(values['max'], int):
                        suggested_value = trial.suggest_int(param_path, values['min'], values['max'])
                    else:
                        suggested_value = trial.suggest_float(param_path, values['min'], values['max'])
            else:
                raise ValueError(f"Invalid optimization param format for {param_path}: {values}")

            self._set_nested_value(config, param_path, suggested_value)

        return config

    def _calculate_score(self, results: dict) -> float:
        """
        Calculate optimization score from backtest results

        Priority: winning trades count, but filtered by profitability
        """
        basic_stats = results.get('basic_stats', {})
        advanced_metrics = results.get('advanced_metrics', {})

        winning_trades = basic_stats.get('winning_trades', 0)
        total_trades = basic_stats.get('total_trades', 0)
        win_rate = basic_stats.get('win_rate', 0)
        profit_factor = advanced_metrics.get('profit_factor', 0)
        total_return = basic_stats.get('total_return', 0)
        sharpe_ratio = advanced_metrics.get('sharpe_ratio', 0)
        max_drawdown = advanced_metrics.get('max_drawdown_percent', 100)

        # Filter: must be profitable
        if profit_factor < 1.0 or total_return <= 0:
            return -999999

        # Filter: must have reasonable number of trades
        if total_trades < 5:
            return -888888

        # Custom metric based on user requirements
        if self.optimization_metric == 'custom_score':
            # Priority: winning trades count * win rate * profit quality
            # Win rate normalized to 0-1
            score = winning_trades * (win_rate / 100) * profit_factor

            # Bonus for higher Sharpe ratio
            if sharpe_ratio > 1.0:
                score *= (1 + sharpe_ratio * 0.1)

            # Penalty for high drawdown
            if max_drawdown > 30:
                score *= 0.8

            return score

        elif self.optimization_metric == 'sharpe_ratio':
            return sharpe_ratio

        elif self.optimization_metric == 'profit_factor':
            return profit_factor

        elif self.optimization_metric == 'total_return':
            return total_return

        elif self.optimization_metric == 'winning_trades':
            # Direct optimization on winning trades count (with profitability filter)
            return winning_trades

        else:
            raise ValueError(f"Unknown optimization metric: {self.optimization_metric}")

    def _objective(self, trial: optuna.Trial) -> float:
        """
        Optuna objective function - runs single backtest and returns score

        Args:
            trial: Optuna trial

        Returns:
            Score to maximize
        """
        try:
            # Create config from trial suggestions
            config = self._create_config_from_trial(trial)

            # Run backtest
            backtester = Backtester(config_dict=config)
            results = backtester.run_backtest(verbose=False)

            # Calculate score
            score = self._calculate_score(results)

            # Store results
            self.all_results.append({
                'trial_number': trial.number,
                'params': trial.params,
                'score': score,
                'results': results
            })

            # Update best
            if score > self.best_score:
                self.best_score = score
                self.best_params = trial.params

            # Progress notification every 20%
            self.trial_count += 1
            progress_pct = (self.trial_count / self.n_trials) * 100

            if self.trial_count % max(1, self.n_trials // 5) == 0:
                self._send_progress_notification(progress_pct)

            return score

        except Exception as e:
            logger.error(f"Trial {trial.number} failed: {e}")
            return -999999

    def _send_notification(self, message: str):
        """Send notification via callback"""
        if self.notification_callback and self.user_id:
            try:
                self.notification_callback(self.user_id, message)
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")

    def _send_progress_notification(self, progress_pct: float):
        """Send progress notification"""
        if not self.notification_callback:
            return

        best_result = None
        for r in self.all_results:
            if r['score'] == self.best_score:
                best_result = r['results']
                break

        if best_result:
            stats = best_result.get('basic_stats', {})
            winning = stats.get('winning_trades', 0)
            win_rate = stats.get('win_rate', 0)
            total_return = stats.get('total_return', 0)

            message = f"📊 Прогресс оптимизации: {self.trial_count}/{self.n_trials} ({progress_pct:.0f}%)\n\n"
            message += f"🏆 Лучший результат:\n"
            message += f"✅ Успешных сделок: {winning}\n"
            message += f"📈 Win Rate: {win_rate:.1f}%\n"
            message += f"💰 Доходность: {total_return:.2f}%\n"
            message += f"⭐Score: {self.best_score:.2f}"
        else:
            message = f"📊 Прогресс: {self.trial_count}/{self.n_trials} ({progress_pct:.0f}%)"

        self._send_notification(message)

    def optimize(self) -> Dict:
        """
        Run Bayesian optimization using Optuna

        Returns:
            Dict with optimization results
        """
        logger.info(f"Starting optimization with {self.n_trials} trials...")

        # Send start notification
        symbol = self.base_config.get('symbol', 'UNKNOWN')
        self._send_notification(
            f"🚀 Запуск оптимизации для {symbol}\n"
            f"🔬 Trials: {self.n_trials}\n"
            f"⏱️ Примерное время: ~{self._estimate_time()} мин"
        )

        start_time = datetime.now()

        # Create Optuna study
        study = optuna.create_study(
            direction='maximize',
            sampler=TPESampler(seed=42),
            pruner=MedianPruner(n_startup_trials=10, n_warmup_steps=5)
        )

        # Run optimization
        study.optimize(
            self._objective,
            n_trials=self.n_trials,
            n_jobs=1,  # We handle parallelism internally
            show_progress_bar=True
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds() / 60

        # Get best results
        best_trial = study.best_trial
        # IMPORTANT: Use params dict to recreate config, NOT trial.suggest_*()
        # trial.suggest_*() only works during active optimization and may generate new random values
        best_config = self._create_config_from_params(best_trial.params)

        # Find best results in stored data
        best_full_results = None
        for r in self.all_results:
            if r['trial_number'] == best_trial.number:
                best_full_results = r['results']
                break

        # Prepare output
        optimization_results = {
            'status': 'completed',
            'best_params': best_trial.params,
            'best_score': best_trial.value,
            'best_config': best_config,
            'best_results': best_full_results,
            'n_trials': self.n_trials,
            'duration_minutes': duration,
            'all_trials': self.all_results[:50],  # Top 50 trials
            'study': study
        }

        # Send completion notification
        self._send_completion_notification(optimization_results)

        logger.info(f"Optimization completed in {duration:.1f} minutes")
        logger.info(f"Best score: {best_trial.value:.2f}")
        logger.info(f"Best params: {best_trial.params}")

        return optimization_results

    def _estimate_time(self) -> int:
        """Estimate optimization time in minutes"""
        # Rough estimate: 30 seconds per backtest
        seconds_per_trial = 30
        total_seconds = (self.n_trials * seconds_per_trial) / self.max_parallel_backtests
        return int(total_seconds / 60)

    def _send_completion_notification(self, results: Dict):
        """Send completion notification with best results"""
        if not self.notification_callback:
            return

        best_results = results.get('best_results', {})
        best_params = results.get('best_params', {})

        if best_results:
            stats = best_results.get('basic_stats', {})
            advanced = best_results.get('advanced_metrics', {})

            message = f"✅ Оптимизация завершена!\n\n"
            message += f"🏆 <b>Лучшие результаты:</b>\n"
            message += f"✅ Успешных сделок: {stats.get('winning_trades', 0)}\n"
            message += f"📊 Всего сделок: {stats.get('total_trades', 0)}\n"
            message += f"📈 Win Rate: {stats.get('win_rate', 0):.1f}%\n"
            message += f"💰 Доходность: {stats.get('total_return', 0):.2f}%\n"
            message += f"📉 Max DD: {advanced.get('max_drawdown_percent', 0):.2f}%\n"
            message += f"⚡ Profit Factor: {advanced.get('profit_factor', 0):.2f}\n"
            message += f"📐 Sharpe Ratio: {advanced.get('sharpe_ratio', 0):.2f}\n\n"

            message += f"🔧 <b>Оптимальные параметры:</b>\n"
            for key, value in best_params.items():
                message += f"• {key}: {value}\n"

            message += f"\n⏱️ Время: {results['duration_minutes']:.1f} мин"
        else:
            message = "✅ Оптимизация завершена, но не найдено прибыльных стратегий"

        self._send_notification(message)

    def walk_forward_validation(self) -> Dict:
        """
        Perform walk-forward validation

        Returns:
            Dict with train/validation/test results
        """
        logger.info("Starting walk-forward validation...")

        # Load data to split
        from data_loader import DataLoader
        loader = DataLoader()

        data_source = self.base_config.get('data_source', {})
        # TODO: Load full dataset and split into periods
        # This is a placeholder - needs proper implementation

        results = {
            'train': None,
            'validation': None,
            'test': None
        }

        return results

    def get_top_n_configs(self, n: int = 10) -> List[Dict]:
        """
        Get top N configurations sorted by score

        Args:
            n: Number of top configs to return

        Returns:
            List of top configurations with results
        """
        sorted_results = sorted(
            self.all_results,
            key=lambda x: x['score'],
            reverse=True
        )

        return sorted_results[:n]

    def export_results(self, filepath: str):
        """Export optimization results to JSON"""
        export_data = {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'n_trials': self.n_trials,
            'optimization_metric': self.optimization_metric,
            'all_results': self.all_results,
            'timestamp': datetime.now().isoformat()
        }

        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"Results exported to {filepath}")
