"""
Проверка «живы ли боты» для пользователя (MCP bots_health): по каждому боту —
в каком он состоянии и получает ли то, что ему нужно для работы:
  SIGNAL              — планировщик сигналов жив и проверял бота на последних свечах;
  WAITING/PYRAMIDING  — бот подписан на поток цен (иначе не увидит стоп/добор);
  PYRAMIDING          — у бота есть открытая позиция;
  IDLE                — если бот циклический с входом по сигналу, IDLE значит,
                        что он выпал из цикла и сам больше не войдёт.
"""
from typing import Dict, Optional

from app.application.signals.check_entry_signal import INTERVAL_MS

# Запас на задержку закрытия свечи (CLOSE_DELAY_SEC) и на сам тик планировщика
GRACE_MS = 3 * 60_000


def assess_bot(
    *,
    state: str,
    config: Dict,
    has_open_position: bool,
    registered_for_prices: bool,
    scheduler_running: bool,
    scheduler_started_ms: Optional[int],
    last_check: Optional[Dict],
    now_ms: int,
) -> Dict:
    issues, notes = [], []
    entry_signal = (config or {}).get("entry_signal")

    if state == "SIGNAL":
        interval = INTERVAL_MS.get((entry_signal or {}).get("timeframe", "15"), 900_000)
        if not entry_signal:
            issues.append("в состоянии SIGNAL, но в конфиге нет entry_signal — не войдёт никогда")
        elif not scheduler_running:
            issues.append("планировщик сигналов не работает — сигналы не проверяются")
        elif last_check is None:
            uptime = now_ms - scheduler_started_ms if scheduler_started_ms else None
            if uptime is not None and uptime < interval + GRACE_MS:
                notes.append("бэкенд недавно перезапущен, первая проверка — на закрытии ближайшей свечи")
            else:
                issues.append("планировщик ни разу не проверял бота с момента запуска бэкенда")
        else:
            age = now_ms - last_check["checked_at_ms"]
            if age > interval + GRACE_MS:
                issues.append(f"последняя проверка сигнала {age // 60_000} мин назад при ТФ {interval // 60_000} мин")
            else:
                notes.append(f"сигнал проверен {age // 60_000} мин назад: {last_check.get('reason', '')}")

    elif state in ("WAITING", "PYRAMIDING", "STRADDLE"):
        if not registered_for_prices:
            issues.append("не подписан на поток цен — стоп, добор и тейк не отслеживаются")
        if state == "PYRAMIDING" and not has_open_position:
            issues.append("в состоянии PYRAMIDING без открытой позиции")

    elif state == "IDLE":
        if (config or {}).get("cycle") and entry_signal:
            issues.append("в IDLE: бот циклический с входом по сигналу, но ожидание сигнала выключено — сам не войдёт")
        else:
            notes.append("остановлен")

    return {"status": "problem" if issues else "ok", "issues": issues, "notes": notes}
