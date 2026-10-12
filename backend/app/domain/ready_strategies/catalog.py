"""
Каталог готовых стратегий: описание + замороженный результат бэктеста.

У стратегии есть варианты (разный размер первого ордера → разный риск).
Стратегия на несколько монет задаётся через legs: при запуске создаётся
по боту на монету, у каждой монеты свои поправки к пресету (например, трейлинг).
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
    # в entry_size_usdt от депозита пользователя. В мультимонетной стратегии —
    # первый ордер каждого бота в % от общего депозита
    first_order_pct_of_deposit: float
    # Поля, которые вариант переопределяет в bot_preset стратегии
    preset_overrides: dict
    backtest_file: str

    def backtest(self) -> dict:
        return _load_backtest(self.backtest_file)


@dataclass(frozen=True)
class StrategyLeg:
    """Монета мультимонетной стратегии: один бот при запуске."""
    symbol: str
    preset_overrides: dict = field(default_factory=dict)


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
    # Пусто — один бот на symbol; иначе по боту на каждую монету
    legs: List[StrategyLeg] = field(default_factory=list)

    @property
    def launch_available(self) -> bool:
        return not self.launch_blockers

    @property
    def launch_legs(self) -> List[StrategyLeg]:
        return self.legs or [StrategyLeg(self.symbol)]

    def variant_preset(self, variant: StrategyVariant, leg: Optional[StrategyLeg] = None) -> dict:
        return {**self.bot_preset, **variant.preset_overrides, **(leg.preset_overrides if leg else {})}


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
    ReadyStrategy(
        slug="alt-short-pyramid-5",
        name="Шорт альтов · пирамидинг · 5 монет",
        summary="Шорт SOL, AVAX, LINK, ETH и XRP в нисходящем тренде 4H: вход на развороте "
                "Supertrend 15m, добор по ходу движения, выход широким трейлингом.",
        description=(
            "Трендовая стратегия на падении альтов. Каждая из пяти монет торгуется своим ботом: "
            "когда монета в нисходящем тренде на 4-часовках (цена и EMA50 ниже EMA200), бот ждёт "
            "разворота Supertrend вниз на 15-минутках и входит в шорт. Пока цена идёт в сторону сделки, "
            "бот добирает ещё 3 ордера того же размера с шагом 0.5%, затем ведёт позицию трейлинг-стопом, "
            "ширина которого подобрана под волатильность монеты (её медианный дневной диапазон). "
            "Тейк-профита нет. Прибыль дают редкие длинные падения; около 80% сделок закрываются "
            "небольшим убытком по стопу 2%. Лонги по тем же правилам убыточны и исключены."
        ),
        symbol="SOLUSDT",
        side="SHORT",
        timeframe="15m",
        entry_rules=[
            "Режим 4H: последняя закрытая 4h-свеча ниже EMA200 и EMA50 ниже EMA200",
            "Триггер 15m: Supertrend(10, 3) развернулся вниз на закрытии свечи",
            "Шорт по рынку на закрытии сигнальной свечи; одна позиция на монету",
            "Пять независимых ботов: SOL, AVAX, LINK, ETH, XRP — депозит делится поровну",
        ],
        exit_rules=[
            "3 добора того же размера по рынку: каждый, когда цена ушла на 0.5% ниже предыдущего "
            "ордера (срабатывание с допуском 0.05% — на −0.45%)",
            "Ордера 1–2: стоп 2% выше цены входа",
            "С 3-го ордера: стоп 2% выше средней цены позиции",
            "С 3-го ордера включается трейлинг: стоп = минимум цены × (1 + трейлинг), но не выше "
            "стопа от средней; трейлинг = медианный дневной диапазон монеты: SOL 8.1%, AVAX 8.0%, "
            "LINK 6.9%, ETH 5.0%, XRP 5.7%. Стоп только опускается",
            "Без тейк-профита: выход только по стопу или трейлингу (рыночным ордером на тике), "
            "затем бот снова ждёт сигнал",
        ],
        risk_notes=[
            "Около 80% сделок убыточны: месяцы и даже годы могут быть около нуля "
            "(2023: +2%, 2024: +10% в консервативном варианте)",
            "Просадка от стартового депозита: до 31% в консервативном и до 63% в агрессивном "
            "варианте (в карточке — от пика equity)",
            "Стоп ограничивает убыток одной сделки, но не серию стопов подряд по всем пяти монетам",
            "Проскальзывание не проверено: входы и доборы — рыночные ордера на тике, при шаге 0.5% "
            "задержка исполнения заметно влияет на результат",
            "В бэктесте шорт только получает funding 0.01%; при отрицательном funding он будет платить",
            "Трейлинг и стоп ведёт бэкенд платформы по тикам цены; на бирже стоит только страховочный "
            "стоп от средней. Если платформа недоступна, трейлинг не двигается",
            "Минимальный лот биржи: при первом ордере меньше ≈$25 вход по ETH может быть отклонён",
            "Трейлинг подобран по истории 2021 — середины 2024; проверка на 07.2024–10.2026 дала "
            "результат не хуже",
        ],
        backtest_assumptions=[
            "Данные: Binance USDT-M futures, 15m OHLC",
            "Вход по close сигнальной свечи, доборы — по уровню при касании, гэп — по цене открытия",
            "Комиссия 0.055% на каждый ордер и выход, стоп с проскальзыванием 0.05%",
            "Funding 0.01% каждые 8 часов на открытый объём",
            "Сопровождение позиции — код живого пирамидинг-бота (PositionCalculator)",
            "Без реинвестирования: первый ордер фиксирован",
        ],
        bot_preset={
            "bot_type": "pyramiding",
            "order_count": 4,  # вход + 3 добора
            "entry_size_usdt": 250,  # переопределяется вариантом
            "step_percent": 0.5,
            "leverage": 10,
            "pyramiding_multiplier": 1.0,
            "sl_initial": 2.0,
            "sl_breakeven_on_order2": False,
            "sl_after_order3": 2.0,
            "use_trailing": True,
            "trailing_percent": 8.1,  # переопределяется монетой
            "tp_percent": 100.0,  # тейка нет — выход по трейлингу
            "cycle": True,
            "entry_signal": {
                "type": "supertrend",
                "timeframe": "15",
                "st_period": 10,
                "st_mult": 3.0,
                "trend_ema_period": 200,
                "trend_ema_fast": 50,
                "trend_timeframe": "240",
            },
        },
        legs=[
            StrategyLeg("SOLUSDT", {"trailing_percent": 8.1}),
            StrategyLeg("AVAXUSDT", {"trailing_percent": 8.0}),
            StrategyLeg("LINKUSDT", {"trailing_percent": 6.9}),
            StrategyLeg("ETHUSDT", {"trailing_percent": 5.0}),
            StrategyLeg("XRPUSDT", {"trailing_percent": 5.7}),
        ],
        launch_blockers=[],
        variants=[
            StrategyVariant(
                key="conservative",
                name="Консервативный",
                description="Первый ордер каждого бота — 5% депозита ($250 на $5 000), вся позиция "
                            "по монете — 20%, по пяти монетам — 1 депозит. Около 22% в год, "
                            "просадка до 31% от стартового депозита.",
                first_order_pct_of_deposit=5.0,
                preset_overrides={"entry_size_usdt": 250},
                backtest_file="alt_short_pyramid_5_250.json",
            ),
            StrategyVariant(
                key="aggressive",
                name="Агрессивный",
                description="Первый ордер каждого бота — 10% депозита ($500 на $5 000), по пяти "
                            "монетам до 2 депозитов объёма. Около 45% в год, просадка до 63% "
                            "от стартового депозита, худший месяц −31%.",
                first_order_pct_of_deposit=10.0,
                preset_overrides={"entry_size_usdt": 500},
                backtest_file="alt_short_pyramid_5_500.json",
            ),
        ],
    ),
]

def list_strategies() -> List[ReadyStrategy]:
    return STRATEGIES


def get_strategy(slug: str) -> Optional[ReadyStrategy]:
    return next((s for s in STRATEGIES if s.slug == slug), None)
