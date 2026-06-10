"""
Telegram Bot for Market Analytics
Provides crypto market insights via Telegram
"""

import asyncio
import os
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ANALYTICS_API_URL = os.getenv('ANALYTICS_API_URL', 'http://market-analytics:8001')

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required!")

# Initialize bot
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ============================================================================
# Helper Functions
# ============================================================================

async def fetch_api(endpoint: str) -> dict:
    """Fetch data from analytics API"""
    url = f"{ANALYTICS_API_URL}{endpoint}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error_text = await resp.text()
                    logger.error(f"API request failed: {resp.status} - {error_text}")
                    return {"error": f"API returned status {resp.status}"}
    except aiohttp.ClientConnectorError as e:
        logger.error(f"API connection error (is market-analytics running?): {url} - {str(e)}")
        return {"error": f"Cannot connect to analytics API: {str(e)}"}
    except asyncio.TimeoutError:
        logger.error(f"API timeout: {url}")
        return {"error": "API request timeout"}
    except Exception as e:
        logger.error(f"API request error: {url} - {type(e).__name__}: {str(e)}")
        return {"error": str(e)}


def format_number(num: float, decimals: int = 2) -> str:
    """Format number with proper decimals"""
    if num is None:
        return "N/A"
    return f"{num:,.{decimals}f}"


def get_trend_emoji(value: float) -> str:
    """Get emoji based on trend direction"""
    if value > 0:
        return "📈"
    elif value < 0:
        return "📉"
    else:
        return "➡️"


def init_database():
    """Initialize database schema and tables if they don't exist"""
    try:
        import psycopg2

        logger.info("Initializing database...")

        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'backtester'),
            user=os.getenv('DB_USER', 'backtester'),
            password=os.getenv('DB_PASSWORD', 'changeme')
        )
        cursor = conn.cursor()

        # Create market_data schema if not exists
        cursor.execute("CREATE SCHEMA IF NOT EXISTS market_data;")

        # Create bot_subscribers table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_data.bot_subscribers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(100),
                first_name VARCHAR(100),
                subscribed_at TIMESTAMPTZ DEFAULT NOW(),
                active BOOLEAN DEFAULT TRUE,
                timezone VARCHAR(50) DEFAULT 'UTC',
                notifications_enabled BOOLEAN DEFAULT TRUE,
                last_notification_at TIMESTAMPTZ
            );
        """)

        # Create indexes if not exist
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscribers_user_id
            ON market_data.bot_subscribers(user_id);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscribers_active
            ON market_data.bot_subscribers(active) WHERE active = TRUE;
        """)

        conn.commit()
        cursor.close()
        conn.close()

        logger.info("✓ Database initialized successfully")

    except Exception as e:
        logger.error(f"✗ Failed to initialize database: {e}")
        logger.warning("Bot will continue, but subscription features may not work")


# ============================================================================
# Command Handlers
# ============================================================================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    welcome_text = f"""
👋 <b>Привет, {message.from_user.first_name}!</b>

Я бот для мониторинга крипто-рынка. Предоставляю актуальные данные и аналитику.

📊 <b>Доступные команды:</b>

/market - Общая сводка рынка
/fear - Индекс страха и жадности
/narrative - Нарратив рынка
/btcdom - Доминация Bitcoin
/macro - Макро показатели
/help - Помощь

🔔 <b>Подписки:</b>
/subscribe - Подписаться на утренние/вечерние сводки
/unsubscribe - Отписаться

Данные обновляются автоматически каждый час.
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Сводка рынка", callback_data="market"),
            InlineKeyboardButton(text="😱 Fear & Greed", callback_data="fear")
        ],
        [
            InlineKeyboardButton(text="🎯 Нарратив", callback_data="narrative"),
            InlineKeyboardButton(text="₿ BTC.D", callback_data="btcdom")
        ]
    ])

    await message.answer(welcome_text, parse_mode='HTML', reply_markup=keyboard)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    help_text = """
📚 <b>Справка по командам:</b>

<b>/market</b> - Получить общую сводку рынка
├─ Fear & Greed Index
├─ BTC Dominance
├─ Altseason Index
└─ Market Narrative

<b>/fear</b> - Индекс страха и жадности (0-100)
└─ Показывает настроение рынка

<b>/narrative</b> - Общий нарратив рынка
└─ Risk-on, Risk-off, Distribution, Accumulation

<b>/btcdom</b> - Доминация Bitcoin
└─ % рыночной капитализации BTC

<b>/macro</b> - Макро показатели
├─ DXY (Dollar Index)
├─ SPX (S&P 500)
├─ NASDAQ
├─ US10Y (Treasury)
└─ GOLD

<b>/subscribe</b> - Подписаться на сводки
└─ Утренняя (6:00 UTC) + Вечерняя (18:00 UTC)

<b>/unsubscribe</b> - Отписаться от сводок

💡 Также можно использовать кнопки ниже команд для быстрого доступа.
"""
    await message.answer(help_text, parse_mode='HTML')


@dp.message(Command("market"))
async def cmd_market(message: Message):
    """Handle /market command - full market summary"""
    await message.answer("📊 Загружаю данные рынка...")

    # Fetch dashboard data
    data = await fetch_api("/api/v1/dashboard")

    if "error" in data:
        await message.answer(f"❌ Ошибка получения данных: {data['error']}")
        return

    # Extract data
    fear_greed = data.get("fear_greed", {})
    btc_dom = data.get("btc_dominance", {})
    altseason = data.get("altseason", {})
    narrative = data.get("narrative", {})

    # Format message
    text = f"""
📊 <b>Сводка крипто-рынка</b>

😱 <b>Fear & Greed Index:</b> {fear_greed.get('value', 'N/A')}
└─ {fear_greed.get('value_classification', 'N/A')}

₿ <b>BTC Dominance:</b> {format_number(btc_dom.get('dominance', 0))}%
└─ {get_trend_emoji(btc_dom.get('change_24h', 0))} {format_number(btc_dom.get('change_24h', 0), 2)}% за 24ч

🌊 <b>Altseason Index:</b> {altseason.get('index', 'N/A')}
└─ {altseason.get('phase', 'N/A')}

🎯 <b>Market Narrative:</b> <b>{narrative.get('narrative', 'N/A')}</b>
└─ Confidence: {format_number(narrative.get('confidence', 0) * 100, 0)}%

⏰ Обновлено: {datetime.utcnow().strftime('%H:%M UTC')}

<i>⚠️ Пока отображаются тестовые данные. Интеграция с реальными источниками в процессе.</i>
"""

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data="market"),
            InlineKeyboardButton(text="📈 Macro", callback_data="macro")
        ]
    ])

    await message.answer(text, parse_mode='HTML', reply_markup=keyboard)


@dp.message(Command("fear"))
async def cmd_fear(message: Message):
    """Handle /fear command - Fear & Greed Index"""
    data = await fetch_api("/api/v1/fear-greed")

    if "error" in data:
        await message.answer(f"❌ Ошибка: {data['error']}")
        return

    # Use mock_data if available
    info = data.get("mock_data", data)

    value = info.get('value', 0)
    classification = info.get('value_classification', 'Unknown')

    # Determine emoji
    if value < 25:
        emoji = "😨"
        zone = "Extreme Fear"
    elif value < 45:
        emoji = "😰"
        zone = "Fear"
    elif value < 55:
        emoji = "😐"
        zone = "Neutral"
    elif value < 75:
        emoji = "😊"
        zone = "Greed"
    else:
        emoji = "🤑"
        zone = "Extreme Greed"

    text = f"""
{emoji} <b>Fear & Greed Index</b>

<b>Значение:</b> {value}/100
<b>Зона:</b> {zone}

📊 <b>Интерпретация:</b>
"""

    if value < 25:
        text += "\n🟢 <i>Extreme Fear - возможность для покупки</i>"
    elif value < 45:
        text += "\n🟡 <i>Fear - осторожный оптимизм</i>"
    elif value < 55:
        text += "\n⚪ <i>Neutral - рынок в равновесии</i>"
    elif value < 75:
        text += "\n🟠 <i>Greed - будьте осторожны</i>"
    else:
        text += "\n🔴 <i>Extreme Greed - возможная коррекция</i>"

    text += f"\n\n⏰ {datetime.utcnow().strftime('%H:%M UTC')}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="fear")]
    ])

    await message.answer(text, parse_mode='HTML', reply_markup=keyboard)


@dp.message(Command("narrative"))
async def cmd_narrative(message: Message):
    """Handle /narrative command - Market Narrative"""
    data = await fetch_api("/api/v1/narrative")

    if "error" in data:
        await message.answer(f"❌ Ошибка: {data['error']}")
        return

    info = data.get("mock_data", data)

    narrative = info.get('narrative', 'Unknown')
    confidence = info.get('confidence', 0) * 100
    components = info.get('components', {})

    # Emoji based on narrative
    emoji_map = {
        'Risk-on': '🚀',
        'Risk-off': '🛑',
        'Distribution': '📤',
        'Accumulation': '📥',
        'Uncertain': '🤔'
    }
    emoji = emoji_map.get(narrative, '❓')

    text = f"""
{emoji} <b>Market Narrative</b>

<b>Нарратив:</b> {narrative}
<b>Уверенность:</b> {format_number(confidence, 0)}%

📊 <b>Компоненты анализа:</b>
├─ Price Action: {components.get('price_action', 'N/A')}
├─ Funding: {components.get('funding', 'N/A')}
├─ Open Interest: {components.get('open_interest', 'N/A')}
├─ Sentiment: {components.get('sentiment', 'N/A')}
└─ BTC Dominance: {components.get('btc_dominance', 'N/A')}

💡 <b>Что это значит:</b>
"""

    if narrative == 'Risk-on':
        text += "\n🟢 <i>Рынок в режиме роста, высокий аппетит к риску</i>"
    elif narrative == 'Risk-off':
        text += "\n🔴 <i>Рынок избегает риска, возможны распродажи</i>"
    elif narrative == 'Accumulation':
        text += "\n🟢 <i>Фаза накопления, хорошо для входа</i>"
    elif narrative == 'Distribution':
        text += "\n🟠 <i>Фаза распределения, будьте осторожны</i>"
    else:
        text += "\n⚪ <i>Неопределенность на рынке</i>"

    text += f"\n\n⏰ {datetime.utcnow().strftime('%H:%M UTC')}"

    await message.answer(text, parse_mode='HTML')


@dp.message(Command("btcdom"))
async def cmd_btcdom(message: Message):
    """Handle /btcdom command - BTC Dominance"""
    data = await fetch_api("/api/v1/btc-dominance")

    if "error" in data:
        await message.answer(f"❌ Ошибка: {data['error']}")
        return

    info = data.get("mock_data", data)

    dominance = info.get('dominance', 0)
    change_24h = info.get('change_24h', 0)
    direction = info.get('direction', 'neutral')

    trend_emoji = get_trend_emoji(change_24h)

    text = f"""
₿ <b>Bitcoin Dominance</b>

<b>Доминация:</b> {format_number(dominance, 2)}%
<b>Изменение 24ч:</b> {trend_emoji} {format_number(change_24h, 2)}%

💡 <b>Интерпретация:</b>
"""

    if change_24h > 0.5:
        text += "\n📈 <i>BTC растет быстрее альтов - возможное давление на альты</i>"
    elif change_24h < -0.5:
        text += "\n📉 <i>BTC.D падает - потенциал для роста альтов</i>"
    else:
        text += "\n➡️ <i>Стабильная доминация - нейтральная фаза</i>"

    text += f"\n\n⏰ {datetime.utcnow().strftime('%H:%M UTC')}"

    await message.answer(text, parse_mode='HTML')


@dp.message(Command("macro"))
async def cmd_macro(message: Message):
    """Handle /macro command - Macro Indicators"""
    data = await fetch_api("/api/v1/macro")

    if "error" in data:
        await message.answer(f"❌ Ошибка: {data['error']}")
        return

    info = data.get("mock_data", data)

    text = f"""
🌍 <b>Макро Индикаторы</b>

💵 <b>DXY (Dollar Index):</b> {format_number(info.get('DXY', {}).get('value', 0), 2)}
└─ {get_trend_emoji(info.get('DXY', {}).get('change_daily', 0))} {format_number(info.get('DXY', {}).get('change_daily', 0), 2)}%

📈 <b>S&P 500:</b> {format_number(info.get('SPX', {}).get('value', 0), 2)}
└─ {get_trend_emoji(info.get('SPX', {}).get('change_daily', 0))} {format_number(info.get('SPX', {}).get('change_daily', 0), 2)}%

💻 <b>NASDAQ:</b> {format_number(info.get('NASDAQ', {}).get('value', 0), 2)}
└─ {get_trend_emoji(info.get('NASDAQ', {}).get('change_daily', 0))} {format_number(info.get('NASDAQ', {}).get('change_daily', 0), 2)}%

📊 <b>US 10Y Treasury:</b> {format_number(info.get('US10Y', {}).get('value', 0), 2)}%
└─ {get_trend_emoji(info.get('US10Y', {}).get('change_daily', 0))} {format_number(info.get('US10Y', {}).get('change_daily', 0), 2)}%

🥇 <b>Gold:</b> ${format_number(info.get('GOLD', {}).get('value', 0), 2)}
└─ {get_trend_emoji(info.get('GOLD', {}).get('change_daily', 0))} {format_number(info.get('GOLD', {}).get('change_daily', 0), 2)}%

⏰ {datetime.utcnow().strftime('%H:%M UTC')}
"""

    await message.answer(text, parse_mode='HTML')


@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """Handle /subscribe command - save user to database"""
    try:
        import psycopg2

        # Connect using separate parameters (safer than DATABASE_URL)
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'backtester'),
            user=os.getenv('DB_USER', 'backtester'),
            password=os.getenv('DB_PASSWORD', 'changeme')
        )
        cursor = conn.cursor()

        # Insert or update subscriber
        cursor.execute("""
            INSERT INTO market_data.bot_subscribers (user_id, username, first_name, active, notifications_enabled)
            VALUES (%s, %s, %s, TRUE, TRUE)
            ON CONFLICT (user_id)
            DO UPDATE SET
                active = TRUE,
                notifications_enabled = TRUE,
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name
        """, (message.from_user.id, message.from_user.username, message.from_user.first_name))

        conn.commit()
        cursor.close()
        conn.close()

        text = """
✅ <b>Вы подписаны на сводки!</b>

Вы будете получать:
• 🌙 Полуночную сводку (00:00 UTC)
• ☀️ Полуденную сводку (12:00 UTC)

Сводки включают:
├─ Fear & Greed Index
├─ BTC Dominance
├─ Altseason Index
├─ Market Narrative
└─ Макро показатели

Отписаться: /unsubscribe
"""
        await message.answer(text, parse_mode='HTML')
        logger.info(f"✓ User {message.from_user.id} subscribed")

    except Exception as e:
        logger.error(f"✗ Failed to subscribe user: {e}")
        await message.answer(f"❌ Ошибка подписки: {str(e)}")


@dp.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    """Handle /unsubscribe command - deactivate subscription"""
    try:
        import psycopg2

        # Connect using separate parameters (safer than DATABASE_URL)
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'backtester'),
            user=os.getenv('DB_USER', 'backtester'),
            password=os.getenv('DB_PASSWORD', 'changeme')
        )
        cursor = conn.cursor()

        # Deactivate subscription
        cursor.execute("""
            UPDATE market_data.bot_subscribers
            SET active = FALSE, notifications_enabled = FALSE
            WHERE user_id = %s
        """, (message.from_user.id,))

        if cursor.rowcount > 0:
            conn.commit()
            text = """
🔕 <b>Вы отписались от сводок</b>

Вы больше не будете получать автоматические уведомления.

Подписаться снова: /subscribe
"""
            logger.info(f"✓ User {message.from_user.id} unsubscribed")
        else:
            text = "ℹ️ Вы не были подписаны на сводки."

        cursor.close()
        conn.close()

        await message.answer(text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"✗ Failed to unsubscribe user: {e}")
        await message.answer(f"❌ Ошибка отписки: {str(e)}")


# ============================================================================
# Callback Query Handlers
# ============================================================================

@dp.callback_query(F.data == "market")
async def callback_market(callback: types.CallbackQuery):
    """Handle market button callback"""
    await callback.answer("Обновляю данные...")
    # Reuse market command logic
    await cmd_market(callback.message)


@dp.callback_query(F.data == "fear")
async def callback_fear(callback: types.CallbackQuery):
    """Handle fear button callback"""
    await callback.answer("Обновляю данные...")
    await cmd_fear(callback.message)


@dp.callback_query(F.data == "narrative")
async def callback_narrative(callback: types.CallbackQuery):
    """Handle narrative button callback"""
    await callback.answer("Обновляю данные...")
    await cmd_narrative(callback.message)


@dp.callback_query(F.data == "btcdom")
async def callback_btcdom(callback: types.CallbackQuery):
    """Handle btcdom button callback"""
    await callback.answer("Обновляю данные...")
    await cmd_btcdom(callback.message)


@dp.callback_query(F.data == "macro")
async def callback_macro(callback: types.CallbackQuery):
    """Handle macro button callback"""
    await callback.answer("Обновляю данные...")
    await cmd_macro(callback.message)


# ============================================================================
# Main Function
# ============================================================================

async def main():
    """Main function to run the bot"""
    logger.info("=" * 60)
    logger.info("Starting Telegram Bot for Market Analytics")
    logger.info(f"Analytics API: {ANALYTICS_API_URL}")
    logger.info("=" * 60)

    # Test API connection
    try:
        health = await fetch_api("/health")
        logger.info(f"✓ API Health Check: {health.get('status', 'unknown')}")
    except Exception as e:
        logger.warning(f"⚠ Could not connect to API: {e}")
        logger.info("Bot will start anyway, but API calls may fail")

    # Initialize database
    init_database()

    # Setup scheduler for notifications
    try:
        from .notifications import setup_scheduler
        scheduler = setup_scheduler(bot)
        scheduler.start()
        logger.info("✓ Notification scheduler started")
    except Exception as e:
        logger.error(f"✗ Failed to start scheduler: {e}")
        logger.info("Bot will continue without scheduled notifications")

    # Start polling
    logger.info("✓ Bot started successfully")
    logger.info("Listening for commands...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
