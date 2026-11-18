from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.bybit_executor import BybitExecutorAdapter
from app.adapters.cryptorg_executor import CryptorgExecutorAdapter
from app.adapters.paper_executor import PaperExecutorAdapter
from app.core.encryption import decrypt
from app.models import Bot
from app.models.bybit_account import BybitAccount
from app.models.cryptorg_account import CryptorgAccount
from app.ports.exchange_executor import ExchangeExecutor
from app.services.cryptorg import get_cryptorg_client


async def build_executor(bot: Bot, db: AsyncSession) -> ExchangeExecutor:
    """Исполнитель для площадки бота (bot.exchange): bybit | paper | cryptorg.
    Use cases зависят только от порта ExchangeExecutor, поэтому выбор
    адаптера живёт здесь — в одном месте для движка и API-роутов."""
    if bot.exchange == "paper":
        return PaperExecutorAdapter()

    if bot.exchange == "bybit":
        if not bot.bybit_account_id:
            raise ValueError(f"Bot {bot.id} has exchange=bybit but no bybit_account_id")
        result = await db.execute(select(BybitAccount).where(BybitAccount.id == bot.bybit_account_id))
        account = result.scalar_one_or_none()
        if not account:
            raise ValueError(f"Bot {bot.id} bybit_account_id={bot.bybit_account_id} not found")
        return BybitExecutorAdapter(
            api_key=decrypt(account.api_key),
            api_secret=decrypt(account.api_secret),
            testnet=account.testnet,
            # straddle держит LONG и SHORT по монете одновременно
            hedge=(bot.config or {}).get("bot_type") == "straddle",
        )

    account = None
    if bot.account_id:
        result = await db.execute(select(CryptorgAccount).where(CryptorgAccount.id == bot.account_id))
        account = result.scalar_one_or_none()
    return CryptorgExecutorAdapter(get_cryptorg_client(account))
