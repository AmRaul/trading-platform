"""
Scheduled Notifications for Telegram Bot
Sends market summaries at 00:00 and 12:00 UTC
"""

import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiohttp
import psycopg2
import os

logger = logging.getLogger(__name__)

# Configuration
ANALYTICS_API_URL = os.getenv('ANALYTICS_API_URL', 'http://market-analytics:8001')


def safe_format_number(value, decimals: int = 2) -> str:
    """Safely format number with None check"""
    if value is None:
        return "N/A"
    try:
        return f"{value:.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


async def fetch_dashboard() -> dict:
    """Fetch dashboard data from analytics API"""
    try:
        url = f"{ANALYTICS_API_URL}/api/v1/dashboard"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.error(f"API returned status {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Failed to fetch dashboard: {e}")
        return None


def get_active_subscribers():
    """Get list of active subscribers from database"""
    try:
        # Connect using separate parameters (safer than DATABASE_URL)
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'backtester'),
            user=os.getenv('DB_USER', 'backtester'),
            password=os.getenv('DB_PASSWORD', 'changeme')
        )
        cursor = conn.cursor()

        cursor.execute("""
            SELECT user_id, username, first_name
            FROM market_data.bot_subscribers
            WHERE active = TRUE AND notifications_enabled = TRUE
        """)

        subscribers = []
        for row in cursor.fetchall():
            subscribers.append({
                'user_id': row[0],
                'username': row[1],
                'first_name': row[2]
            })

        cursor.close()
        conn.close()

        logger.info(f"Found {len(subscribers)} active subscribers")
        return subscribers

    except Exception as e:
        logger.error(f"Failed to get subscribers: {e}")
        return []


def format_notification_message(data: dict, time_label: str) -> str:
    """Format market data into notification message"""
    if not data:
        return f"⚠️ Не удалось получить данные рынка для {time_label} сводки"

    try:
        fear_greed = data.get('fear_greed', {})
        btc_dom = data.get('btc_dominance', {})
        altseason = data.get('altseason', {})
        narrative = data.get('narrative', {})
        macro = data.get('macro', {})

        # Emoji based on narrative
        narrative_emoji = {
            'Risk-on': '🚀',
            'Risk-off': '🛑',
            'Accumulation': '📥',
            'Distribution': '📤',
            'Uncertain': '🤔'
        }.get(narrative.get('narrative', 'Uncertain'), '❓')

        message = f"""
🌅 <b>{time_label} Сводка Крипто-Рынка</b>

📊 <b>Основные Метрики:</b>

😱 <b>Fear & Greed:</b> {fear_greed.get('value', 'N/A')}
└─ {fear_greed.get('value_classification', 'N/A')}

₿ <b>BTC Dominance:</b> {safe_format_number(btc_dom.get('dominance'))}%
└─ {"📈" if (btc_dom.get('change_24h') or 0) > 0 else "📉"} {safe_format_number(btc_dom.get('change_24h'))}% за 24ч

🌊 <b>Altseason Index:</b> {altseason.get('index', 'N/A')}
└─ {altseason.get('phase', 'N/A')}

{narrative_emoji} <b>Market Narrative:</b> <b>{narrative.get('narrative', 'N/A')}</b>
└─ Confidence: {safe_format_number((narrative.get('confidence') or 0) * 100, 0)}%

🌍 <b>Макро Обзор:</b>
"""

        # Add macro if available
        if macro and not isinstance(macro, dict):
            macro = {}

        for key in ['DXY', 'SPX', 'NASDAQ']:
            if key in macro:
                val = macro[key].get('value')
                change = macro[key].get('change_daily')
                emoji = "📈" if (change or 0) > 0 else "📉" if (change or 0) < 0 else "➡️"
                message += f"  {key}: {safe_format_number(val)} ({emoji} {safe_format_number(change, 2):>6}%)\n"

        message += f"\n⏰ <i>{datetime.utcnow().strftime('%d.%m.%Y %H:%M UTC')}</i>"

        return message

    except Exception as e:
        logger.error(f"Error formatting message: {e}")
        return f"⚠️ Ошибка форматирования сводки: {str(e)}"


async def send_notification(bot, subscriber: dict, message: str):
    """Send notification to a single subscriber"""
    try:
        await bot.send_message(
            chat_id=subscriber['user_id'],
            text=message,
            parse_mode='HTML'
        )
        logger.info(f"✓ Sent notification to {subscriber.get('username', subscriber['user_id'])}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to send to {subscriber['user_id']}: {e}")
        return False


async def send_market_summary(bot, time_label: str):
    """
    Send market summary to all active subscribers

    Args:
        bot: Telegram bot instance
        time_label: "Утренняя" or "Вечерняя"
    """
    logger.info(f"=" * 60)
    logger.info(f"Sending {time_label} market summary...")
    logger.info(f"=" * 60)

    # Fetch dashboard data
    data = await fetch_dashboard()

    if not data:
        logger.error("No data available, skipping notifications")
        return

    # Get active subscribers
    subscribers = get_active_subscribers()

    if not subscribers:
        logger.warning("No active subscribers found")
        return

    # Format message
    message = format_notification_message(data, time_label)

    # Send to all subscribers
    success_count = 0
    fail_count = 0

    for subscriber in subscribers:
        result = await send_notification(bot, subscriber, message)
        if result:
            success_count += 1
        else:
            fail_count += 1

        # Small delay to avoid rate limits
        await asyncio.sleep(0.1)

    logger.info(f"✓ Notifications sent: {success_count} success, {fail_count} failed")
    logger.info(f"=" * 60)


def setup_scheduler(bot):
    """
    Setup APScheduler for automatic notifications

    Sends notifications at:
    - 00:00 UTC (Midnight summary)
    - 12:00 UTC (Noon summary)
    """
    scheduler = AsyncIOScheduler()

    # Midnight summary (00:00 UTC)
    scheduler.add_job(
        send_market_summary,
        trigger=CronTrigger(hour=0, minute=0, timezone='UTC'),
        args=[bot, "Полуночная"],
        id='midnight_summary',
        name='Midnight Market Summary',
        replace_existing=True
    )

    # Noon summary (12:00 UTC)
    scheduler.add_job(
        send_market_summary,
        trigger=CronTrigger(hour=12, minute=0, timezone='UTC'),
        args=[bot, "Полуденная"],
        id='noon_summary',
        name='Noon Market Summary',
        replace_existing=True
    )

    logger.info("✓ Scheduler configured:")
    logger.info("  - Midnight summary: 00:00 UTC")
    logger.info("  - Noon summary: 12:00 UTC")

    return scheduler


# ============================================================================
# Optimization Notifications
# ============================================================================

async def send_optimization_notification_async(bot, user_id: str, message: str):
    """
    Send optimization notification to specific user (async version)

    Args:
        bot: Telegram bot instance
        user_id: Telegram user ID
        message: Notification message
    """
    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=message,
            parse_mode='HTML'
        )
        logger.info(f"✓ Sent optimization notification to {user_id}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to send optimization notification to {user_id}: {e}")
        return False


def send_optimization_notification(user_id: str, message: str):
    """
    Send optimization notification (sync wrapper for use in optimizer.py)

    Args:
        user_id: Telegram user ID
        message: Notification message
    """
    try:
        import telegram
        import os

        BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
        if not BOT_TOKEN:
            logger.warning("TELEGRAM_BOT_TOKEN not set, skipping notification")
            return False

        bot = telegram.Bot(token=BOT_TOKEN)

        # Use sync version of send_message
        bot.send_message(
            chat_id=int(user_id),
            text=message,
            parse_mode='HTML'
        )

        logger.info(f"✓ Sent optimization notification to {user_id}")
        return True

    except Exception as e:
        logger.error(f"✗ Failed to send optimization notification: {e}")
        return False
