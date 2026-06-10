#!/usr/bin/env python3
"""
Live Signal Generator for Cryptocurrency Trading
Monitors market in real-time and generates trading signals based on configured strategies
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
import ccxt.async_support as ccxt
import pandas as pd
import psycopg2
from psycopg2.extras import Json
import argparse

# Import local modules
from strategy import TradingStrategy
from indicators import IndicatorStrategy, TechnicalIndicators

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveSignalGenerator:
    """
    Real-time trading signal generator

    Monitors cryptocurrency markets and generates signals based on
    indicator strategies (RSI, EMA, ADX, MACD, etc.)
    """

    def __init__(
        self,
        config_path: str,
        telegram_user_id: Optional[str] = None,
        exchange_name: str = 'binance',
        dry_run: bool = True
    ):
        """
        Initialize signal generator

        Args:
            config_path: Path to strategy config JSON file
            telegram_user_id: Telegram user ID for notifications
            exchange_name: Exchange to connect to (default: binance)
            dry_run: If True, only log signals without saving to DB
        """
        self.config_path = config_path
        self.telegram_user_id = telegram_user_id
        self.exchange_name = exchange_name
        self.dry_run = dry_run

        # Load configuration
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # Extract parameters
        self.symbol = self.config.get('data_source', {}).get('symbol', 'BTC/USDT')
        self.timeframe = self.config.get('timeframe', '15m')
        self.order_type = self.config.get('order_type', 'long')

        # Initialize exchange
        self.exchange = None

        # Initialize strategy components
        self.strategy = None
        self.indicator_strategy = None

        # State management
        self.is_running = False
        self.last_signal_time = None
        self.last_candle_time = None
        self.historical_data = pd.DataFrame()

        # Signal cooldown (prevent duplicate signals)
        self.signal_cooldown_minutes = 5

        # Database connection
        self.db_conn = None

        logger.info(f"Initialized LiveSignalGenerator for {self.symbol} on {self.timeframe}")
        logger.info(f"Strategy: {self.config.get('indicators', {}).get('strategy_type', 'manual')}")
        logger.info(f"Dry run mode: {self.dry_run}")

    async def connect_exchange(self):
        """Connect to cryptocurrency exchange"""
        try:
            exchange_class = getattr(ccxt, self.exchange_name)
            self.exchange = exchange_class({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'  # Use futures market
                }
            })
            await self.exchange.load_markets()
            logger.info(f"✓ Connected to {self.exchange_name}")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to {self.exchange_name}: {e}")
            return False

    def connect_database(self):
        """Connect to PostgreSQL database"""
        if self.dry_run:
            logger.info("Dry run mode: skipping database connection")
            return True

        try:
            self.db_conn = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                port=os.getenv('DB_PORT', '5432'),
                database=os.getenv('DB_NAME', 'backtester'),
                user=os.getenv('DB_USER', 'backtester'),
                password=os.getenv('DB_PASSWORD', 'changeme')
            )
            logger.info("✓ Connected to PostgreSQL database")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to database: {e}")
            return False

    async def fetch_ohlcv(self, limit: int = 200) -> pd.DataFrame:
        """
        Fetch OHLCV data from exchange

        Args:
            limit: Number of candles to fetch

        Returns:
            DataFrame with OHLCV data
        """
        try:
            ohlcv = await self.exchange.fetch_ohlcv(
                self.symbol,
                self.timeframe,
                limit=limit
            )

            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            return df

        except Exception as e:
            logger.error(f"Error fetching OHLCV: {e}")
            return pd.DataFrame()

    def initialize_strategy(self):
        """Initialize trading strategy with indicators"""
        try:
            self.strategy = TradingStrategy(
                start_balance=self.config.get('start_balance', 10000),
                config=self.config
            )

            # Initialize indicator strategy if enabled
            if self.config.get('indicators', {}).get('enabled', False):
                self.indicator_strategy = IndicatorStrategy()

            logger.info("✓ Strategy initialized")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to initialize strategy: {e}")
            return False

    def check_signal_conditions(
        self,
        current_candle: pd.Series,
        historical_data: pd.DataFrame
    ) -> Optional[Dict[str, Any]]:
        """
        Check if signal conditions are met

        Args:
            current_candle: Latest candle data
            historical_data: Historical OHLCV data

        Returns:
            Signal dict if conditions met, None otherwise
        """
        try:
            # Check if indicators are enabled
            if not self.config.get('indicators', {}).get('enabled', False):
                logger.debug("Indicators disabled, skipping signal check")
                return None

            # Check if we're in cooldown period
            if self.last_signal_time:
                time_since_last = datetime.now() - self.last_signal_time
                if time_since_last < timedelta(minutes=self.signal_cooldown_minutes):
                    logger.debug(f"In cooldown period ({time_since_last.seconds}s since last signal)")
                    return None

            # Use strategy to check entry conditions
            should_enter = self.strategy.should_enter_position(
                current_candle,
                historical_data
            )

            if not should_enter:
                return None

            # Signal detected! Gather indicator values
            indicators_config = self.config.get('indicators', {})
            strategy_type = indicators_config.get('strategy_type', 'custom')

            # Get indicator values using IndicatorStrategy
            signal_data = None

            if strategy_type == 'trend_momentum':
                signal_data = self.indicator_strategy.trend_momentum_signal(
                    historical_data,
                    indicators_config.get('trend_momentum', {})
                )
            elif strategy_type == 'volatility_bounce':
                signal_data = self.indicator_strategy.volatility_bounce_signal(
                    historical_data,
                    indicators_config.get('volatility_bounce', {})
                )
            elif strategy_type == 'momentum_trend':
                signal_data = self.indicator_strategy.momentum_trend_signal(
                    historical_data,
                    indicators_config.get('momentum_trend', {})
                )
            elif strategy_type == 'custom':
                signal_data = self.indicator_strategy.custom_signal(
                    historical_data,
                    indicators_config.get('custom', {})
                )

            if not signal_data:
                return None

            # Check if signal matches our order type
            is_long_signal = signal_data.get('long_signal', False)
            is_short_signal = signal_data.get('short_signal', False)

            if self.order_type == 'long' and not is_long_signal:
                return None
            if self.order_type == 'short' and not is_short_signal:
                return None

            # Build signal object
            entry_price = float(current_candle['close'])

            # Calculate TP/SL prices
            tp_config = self.config.get('take_profit', {})
            sl_config = self.config.get('stop_loss', {})

            tp_percent = tp_config.get('target_percent', 3.0) if tp_config.get('enabled') else None
            sl_percent = sl_config.get('stop_percent', 2.0) if sl_config.get('enabled') else None

            if self.order_type == 'long':
                tp_price = entry_price * (1 + tp_percent / 100) if tp_percent else None
                sl_price = entry_price * (1 - sl_percent / 100) if sl_percent else None
            else:  # short
                tp_price = entry_price * (1 - tp_percent / 100) if tp_percent else None
                sl_price = entry_price * (1 + sl_percent / 100) if sl_percent else None

            # Extract DCA config if enabled
            dca_config = self.config.get('dca', {})
            dca_enabled = dca_config.get('enabled', False)
            dca_grid = None

            if dca_enabled:
                # Build DCA grid
                max_orders = dca_config.get('max_orders', 3)
                step_config = dca_config.get('step_price', {})
                step_percent = step_config.get('value', 1.5)

                dca_grid = []
                for i in range(1, max_orders + 1):
                    if self.order_type == 'long':
                        dca_price = entry_price * (1 - (step_percent * i) / 100)
                    else:
                        dca_price = entry_price * (1 + (step_percent * i) / 100)

                    dca_grid.append({
                        'step': i,
                        'price': round(dca_price, 8),
                        'percent_from_entry': -step_percent * i if self.order_type == 'long' else step_percent * i
                    })

            signal = {
                'timestamp': datetime.now(),
                'symbol': self.symbol,
                'timeframe': self.timeframe,
                'exchange': self.exchange_name,
                'side': self.order_type,
                'entry_price': entry_price,
                'take_profit_percent': tp_percent,
                'take_profit_price': tp_price,
                'stop_loss_percent': sl_percent,
                'stop_loss_price': sl_price,
                'dca_enabled': dca_enabled,
                'dca_grid': dca_grid,
                'indicators': signal_data.get('indicators', {}),
                'strategy_name': f"{strategy_type}_{self.order_type}",
                'strategy_config': self.config.get('indicators'),
                'quality_score': self._calculate_quality_score(signal_data)
            }

            return signal

        except Exception as e:
            logger.error(f"Error checking signal conditions: {e}", exc_info=True)
            return None

    def _calculate_quality_score(self, signal_data: Dict) -> float:
        """
        Calculate signal quality score (0-100)
        Based on indicator confluence and conditions met
        """
        score = 50.0  # Base score

        # Add points for each indicator condition met
        indicators = signal_data.get('indicators', {})

        # RSI conditions
        if 'rsi' in indicators:
            rsi = indicators['rsi']
            if 20 <= rsi <= 30 or 70 <= rsi <= 80:
                score += 15  # Strong oversold/overbought
            elif 30 <= rsi <= 40 or 60 <= rsi <= 70:
                score += 10  # Moderate

        # Trend alignment (EMA)
        if signal_data.get('trend_up') or signal_data.get('trend_down'):
            score += 20  # Trend confirmation

        # Volatility indicators (ADX, Bollinger)
        if 'adx' in indicators:
            adx = indicators['adx']
            if adx < 25:  # Low volatility (good for bounce)
                score += 10
            elif adx > 25:  # Strong trend
                score += 5

        # MACD confirmation
        if 'macd_histogram' in indicators:
            score += 5

        return min(100.0, score)

    async def save_signal_to_db(self, signal: Dict[str, Any]) -> bool:
        """
        Save signal to PostgreSQL database

        Args:
            signal: Signal dictionary

        Returns:
            True if saved successfully
        """
        if self.dry_run:
            logger.info("Dry run mode: signal not saved to database")
            return True

        try:
            cursor = self.db_conn.cursor()

            cursor.execute("""
                INSERT INTO backtester.trading_signals (
                    timestamp, symbol, timeframe, exchange,
                    side, entry_price,
                    take_profit_percent, take_profit_price,
                    stop_loss_percent, stop_loss_price,
                    dca_enabled, dca_grid,
                    indicators, strategy_name, strategy_config,
                    telegram_user_id, quality_score
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                RETURNING signal_id
            """, (
                signal['timestamp'],
                signal['symbol'],
                signal['timeframe'],
                signal['exchange'],
                signal['side'],
                signal['entry_price'],
                signal['take_profit_percent'],
                signal['take_profit_price'],
                signal['stop_loss_percent'],
                signal['stop_loss_price'],
                signal['dca_enabled'],
                Json(signal['dca_grid']) if signal['dca_grid'] else None,
                Json(signal['indicators']),
                signal['strategy_name'],
                Json(signal['strategy_config']),
                self.telegram_user_id,
                signal['quality_score']
            ))

            signal_id = cursor.fetchone()[0]
            self.db_conn.commit()
            cursor.close()

            logger.info(f"✓ Signal saved to database (ID: {signal_id})")
            return True

        except Exception as e:
            logger.error(f"✗ Failed to save signal to database: {e}")
            if self.db_conn:
                self.db_conn.rollback()
            return False

    async def send_telegram_notification(self, signal: Dict[str, Any]) -> bool:
        """
        Send signal notification via Telegram

        Args:
            signal: Signal dictionary

        Returns:
            True if sent successfully
        """
        if not self.telegram_user_id:
            logger.info("No Telegram user ID configured, skipping notification")
            return False

        try:
            # Import Telegram notification function
            from market_analytics.bot.notifications import send_optimization_notification

            # Format message
            message = self._format_telegram_message(signal)

            # Send notification
            success = send_optimization_notification(
                self.telegram_user_id,
                message
            )

            if success:
                logger.info(f"✓ Telegram notification sent to {self.telegram_user_id}")
            else:
                logger.warning("✗ Failed to send Telegram notification")

            return success

        except ImportError:
            logger.warning("Telegram bot module not available")
            return False
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
            return False

    def _format_telegram_message(self, signal: Dict[str, Any]) -> str:
        """Format signal as Telegram message"""
        side_emoji = "🟢" if signal['side'] == 'long' else "🔴"

        indicators = signal.get('indicators', {})
        rsi = indicators.get('rsi', 'N/A')
        ema_50 = indicators.get('ema_50', 'N/A')
        adx = indicators.get('adx', 'N/A')

        message = f"""
{side_emoji} <b>TRADING SIGNAL</b> {side_emoji}

📊 <b>Market:</b> {signal['symbol']}
⏰ <b>Timeframe:</b> {signal['timeframe']}
📈 <b>Side:</b> {signal['side'].upper()}
💰 <b>Entry:</b> ${signal['entry_price']:,.2f}

🎯 <b>Take Profit:</b> {signal['take_profit_percent']:.2f}% (${signal['take_profit_price']:,.2f})
🛑 <b>Stop Loss:</b> {signal['stop_loss_percent']:.2f}% (${signal['stop_loss_price']:,.2f})

📉 <b>Indicators:</b>
  RSI: {rsi if isinstance(rsi, str) else f"{rsi:.2f}"}
  EMA50: {ema_50 if isinstance(ema_50, str) else f"{ema_50:.2f}"}
  ADX: {adx if isinstance(adx, str) else f"{adx:.2f}"}

⭐ <b>Quality Score:</b> {signal.get('quality_score', 0):.0f}/100

🕐 <i>{signal['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}</i>
"""

        if signal.get('dca_enabled') and signal.get('dca_grid'):
            message += "\n<b>DCA Grid:</b>\n"
            for step in signal['dca_grid'][:3]:  # Show first 3 steps
                message += f"  Step {step['step']}: ${step['price']:,.2f} ({step['percent_from_entry']:+.2f}%)\n"

        return message

    async def process_signal(self, signal: Dict[str, Any]):
        """
        Process detected signal

        Args:
            signal: Signal dictionary
        """
        logger.info("=" * 60)
        logger.info("📡 SIGNAL DETECTED!")
        logger.info(f"Symbol: {signal['symbol']}")
        logger.info(f"Side: {signal['side'].upper()}")
        logger.info(f"Entry: ${signal['entry_price']:,.2f}")
        logger.info(f"TP: {signal['take_profit_percent']:.2f}% | SL: {signal['stop_loss_percent']:.2f}%")
        logger.info(f"Quality: {signal.get('quality_score', 0):.0f}/100")
        logger.info("=" * 60)

        # Save to database
        await self.save_signal_to_db(signal)

        # Send Telegram notification
        await self.send_telegram_notification(signal)

        # Update last signal time
        self.last_signal_time = datetime.now()

    async def run(self):
        """Main loop - monitor market and generate signals"""
        logger.info("=" * 60)
        logger.info("Starting Live Signal Generator")
        logger.info("=" * 60)

        # Connect to exchange
        if not await self.connect_exchange():
            logger.error("Failed to connect to exchange, exiting")
            return

        # Connect to database
        if not self.connect_database():
            logger.error("Failed to connect to database, exiting")
            return

        # Initialize strategy
        if not self.initialize_strategy():
            logger.error("Failed to initialize strategy, exiting")
            return

        # Fetch initial historical data
        logger.info("Fetching initial historical data...")
        self.historical_data = await self.fetch_ohlcv(limit=200)

        if self.historical_data.empty:
            logger.error("Failed to fetch initial data, exiting")
            return

        logger.info(f"✓ Loaded {len(self.historical_data)} historical candles")
        logger.info(f"Monitoring {self.symbol} on {self.timeframe}...")
        logger.info(f"Press Ctrl+C to stop")
        logger.info("=" * 60)

        self.is_running = True

        try:
            while self.is_running:
                try:
                    # Fetch latest data
                    latest_data = await self.fetch_ohlcv(limit=50)

                    if latest_data.empty:
                        logger.warning("No data received, retrying...")
                        await asyncio.sleep(10)
                        continue

                    # Check if we have a new candle
                    latest_candle_time = latest_data.iloc[-1]['timestamp']

                    if self.last_candle_time and latest_candle_time <= self.last_candle_time:
                        # No new candle yet, wait
                        await asyncio.sleep(5)
                        continue

                    # New candle detected
                    self.last_candle_time = latest_candle_time
                    current_candle = latest_data.iloc[-1]

                    logger.info(f"New candle: {current_candle['timestamp']} | Close: ${current_candle['close']:,.2f}")

                    # Update historical data
                    self.historical_data = latest_data

                    # Check for signal
                    signal = self.check_signal_conditions(
                        current_candle,
                        self.historical_data
                    )

                    if signal:
                        await self.process_signal(signal)

                    # Wait before next check
                    await asyncio.sleep(10)

                except KeyboardInterrupt:
                    logger.info("\nReceived interrupt signal, stopping...")
                    break

                except Exception as e:
                    logger.error(f"Error in main loop: {e}", exc_info=True)
                    await asyncio.sleep(30)

        finally:
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources"""
        logger.info("Cleaning up resources...")

        self.is_running = False

        if self.exchange:
            await self.exchange.close()
            logger.info("✓ Exchange connection closed")

        if self.db_conn:
            self.db_conn.close()
            logger.info("✓ Database connection closed")

        logger.info("✓ Cleanup complete")


async def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description='Live Trading Signal Generator')
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to strategy configuration JSON file'
    )
    parser.add_argument(
        '--telegram-user-id',
        type=str,
        help='Telegram user ID for notifications'
    )
    parser.add_argument(
        '--exchange',
        type=str,
        default='binance',
        help='Exchange name (default: binance)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Dry run mode (do not save to database)'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Live mode (save to database and send notifications)'
    )

    args = parser.parse_args()

    # Check if config file exists
    if not Path(args.config).exists():
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    # Create generator
    generator = LiveSignalGenerator(
        config_path=args.config,
        telegram_user_id=args.telegram_user_id,
        exchange_name=args.exchange,
        dry_run=not args.live
    )

    # Run
    try:
        await generator.run()
    except KeyboardInterrupt:
        logger.info("\nStopping signal generator...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
