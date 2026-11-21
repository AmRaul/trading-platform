"""Когда слать алерт: проблема появилась, ушла, держится долго (напоминание).
Та же логика, что у services/alerter (там — ещё и «бэкенд лежит»), здесь — для
личных алертов пользователей по их ботам (services/user_alerts.py)."""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


def problem_key(scope: str, text: str) -> str:
    """Ключ без чисел: «тик 7 мин назад» и «тик 12 мин назад» — одна и та же проблема."""
    return f"{scope}:{re.sub(r'[0-9.,]+', '#', text)}"


def bot_problems(report: Dict) -> Dict[str, str]:
    """{ключ: текст} из bots-health пользователя."""
    out: Dict[str, str] = {}
    for b in report.get("bots", []):
        if b.get("status") != "problem":
            continue
        for issue in b.get("issues", []):
            out[problem_key(f"bot:{b['bot_id']}", issue)] = f"{b.get('name') or b['bot_id']} ({b.get('symbol', '')}): {issue}"
    return out


@dataclass
class AlertState:
    remind_sec: float = 6 * 3600
    active: Dict[str, Tuple[str, float, float]] = field(default_factory=dict)  # key -> (текст, с какого, последнее)

    def update(self, problems: Dict[str, str], now: float) -> List[str]:
        new = [(k, t) for k, t in problems.items() if k not in self.active]
        gone = [(k, self.active[k][0]) for k in list(self.active) if k not in problems]
        remind = [(k, problems[k], since) for k, (_, since, sent) in self.active.items()
                  if k in problems and now - sent >= self.remind_sec]
        msgs: List[str] = []
        if new:
            msgs.append("🔴 kandle: проблема\n" + "\n".join(f"• {t}" for _, t in new))
        if gone:
            msgs.append("✅ kandle: восстановилось\n" + "\n".join(f"• {t}" for _, t in gone))
        if remind:
            msgs.append("⏰ kandle: всё ещё не так\n" + "\n".join(
                f"• {t} (уже {int((now - since) // 3600)} ч)" for _, t, since in remind))
        for k, t in new:
            self.active[k] = (t, now, now)
        for k, _ in gone:
            del self.active[k]
        for k, t, since in remind:
            self.active[k] = (t, since, now)
        return msgs
