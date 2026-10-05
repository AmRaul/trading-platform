"""
Каталог готовых стратегий: описание + замороженный результат бэктеста.

У стратегии есть варианты (разный размер первого ордера → разный риск).
Результаты бэктеста каждого варианта лежат в data/*.json и генерируются
скриптами из services/backtester/research/ — руками не редактируются.
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class StrategyVariant:
    key: str
    name: str
    description: str
    # Размер первого ордера в % от депозита — при запуске пересчитывается
    # в entry_size_usdt от баланса пользователя
    first_order_pct_of_deposit: float
    # Поля, которые вариант переопределяет в bot_preset стратегии
    preset_overrides: dict
    backtest_file: str

    def backtest(self) -> dict:
        return _load_backtest(self.backtest_file)


@dataclass(frozen=True)
class ReadyStrategy:
    slug: str
    name: str
    summary: str
    description: str
    symbol: str
    side: str
    timeframe: str
    entry_rules: List[str]
    exit_rules: List[str]
    risk_notes: List[str]
    backtest_assumptions: List[str]
    # Конфиг бота (StrategyConfig) для будущего запуска в один клик
    bot_preset: dict
    # Первый вариант — вариант по умолчанию
    variants: List[StrategyVariant]
    # Пока непустой — запуск недоступен, показываем причины
    launch_blockers: List[str] = field(default_factory=list)

    @property
    def launch_available(self) -> bool:
        return not self.launch_blockers

    def variant_preset(self, variant: StrategyVariant) -> dict:
        return {**self.bot_preset, **variant.preset_overrides}


@lru_cache
def _load_backtest(filename: str) -> dict:
    return json.loads((DATA_DIR / filename).read_text())


STRATEGIES: List[ReadyStrategy] = [
    ReadyStrategy(
        slug="mrc-dca-btc-15m-long",
        name="MRC DCA · BTC 15m Long",
        summary="Покупка перепроданности по Mean Reversion Channel с сеткой из 4 страховочных, "
                "только в восходящем тренде (BTC выше EMA200 на дневке).",
        description=(
            "Стратегия возврата к среднему. Бот входит в лонг, когда цена на 15-минутках уходит "
            "во вторую нижнюю полосу Mean Reversion Channel — то есть заметно ниже своей средней. "
            "Если цена продолжает падать, сетка докупает 4 страховочных ордера с шагом 1.55% и "
            "удвоением объёма, а тейк-профит пересчитывается от средней цены. Входы разрешены "
            "только когда дневная свеча BTC закрылась выше EMA200 — в медвежьем рынке бот не торгует. "
            "Шорт-сторона протестирована и сознательно исключена: в бэктесте 2021–2026 она "
            "убыточна или ликвидируется при любых настройках."
        ),
        symbol="BTCUSDT",
        side="LONG",
        timeframe="15m",
        entry_rules=[
            "MRC (length 200, outer 2.415, hlc3) на 15m: цена во 2-й нижней полосе (risk zone −2)",
            "Фильтр тренда: последняя закрытая дневная свеча BTC выше EMA200",
            "Одна позиция за раз; новый вход только по новому сигналу после закрытия",
        ],
        exit_rules=[
            "Тейк-профит 0.97% от средней цены позиции",
            "4 страховочных ордера: шаг 1.55% от предыдущего, объём ×2 (1-2-4-8-16)",
            "Аварийный стоп 20% от средней цены — только после заполнения всей сетки",
        ],
        risk_notes=[
            "Полная сетка = 31 × первый ордер: ~1.5 депозита объёма в консервативном варианте, "
            "~3 депозита — в агрессивном",
            "Стратегия зарабатывает много маленьких сделок; один стоп стоит примерно год прибыли",
            "Фильтр EMA200 выбран по той же истории, на которой показан результат — "
            "честной проверки на отложенных данных пока нет",
            "С теми же параметрами: ETH +64% (просадка 17%), SOL +45% (15%) — но AVAX, LINK, DOGE и BNB "
            "уходят в убыток с просадкой 78–90%. Стратегия рассчитана только на BTC",
            "Live-страховочные — рыночные ордера при касании уровня (в бэктесте — лимитные по уровню): "
            "возможно небольшое проскальзывание",
            "На Cryptorg бот не видит ручное закрытие или ликвидацию на бирже — только TP/стоп по цене; "
            "на Bybit позиция дополнительно сверяется с биржей раз в минуту",
        ],
        backtest_assumptions=[
            "Данные: Binance USDT-M futures, 15m OHLC",
            "Страховочные исполняются по своей лимитной цене при касании; гэп — по цене открытия",
            "Комиссии: 0.055% taker (вход, страховочные, стоп), 0.02% maker (тейк)",
            "Funding 0.01% каждые 8 часов на открытый объём",
            "Без реинвестирования: первый ордер фиксирован",
        ],
        bot_preset={
            "bot_type": "dca",
            "order_count": 5,  # вход + 4 страховочных
            "entry_size_usdt": 280,  # переопределяется вариантом
            "step_percent": 1.55,
            "leverage": 10,
            "dca_multiplier": 2.0,
            "dca_multiplier_price": 1.0,
            "tp_percent": 0.97,
            "sl_initial": 20.0,
            "use_trailing": False,
            "cycle": True,
            "entry_signal": {
                "type": "mrc",
                "timeframe": "15",
                "mrc_length": 200,
                "mrc_inner_mult": 1.0,
                "mrc_outer_mult": 2.415,
                "mrc_gradsize": 0.5,
                "mrc_source": "hlc3",
                "entry_band": 2,
                "trend_ema_period": 200,
                "trend_timeframe": "D",
            },
        },
        launch_blockers=[],
        variants=[
            StrategyVariant(
                key="conservative",
                name="Консервативный",
                description="Первый ордер ≈5% депозита ($280 на $5 700). Около 10% в год, "
                            "максимальная просадка 15%.",
                first_order_pct_of_deposit=4.9,
                preset_overrides={"entry_size_usdt": 280},
                backtest_file="mrc_dca_btc_15m_long.json",
            ),
            StrategyVariant(
                key="aggressive",
                name="Агрессивный",
                description="Первый ордер ≈10% депозита ($560 на $5 700). Около 20% в год, "
                            "максимальная просадка 26%. Ликвидация на истории наступила бы "
                            "только при первом ордере ≈$8 000, но будущий худший случай может быть глубже.",
                first_order_pct_of_deposit=9.8,
                preset_overrides={"entry_size_usdt": 560},
                backtest_file="mrc_dca_btc_15m_long_aggressive.json",
            ),
        ],
    ),
]


def list_strategies() -> List[ReadyStrategy]:
    return STRATEGIES


def get_strategy(slug: str) -> Optional[ReadyStrategy]:
    return next((s for s in STRATEGIES if s.slug == slug), None)
